"""
ASGI 版本的 HTTP 服务器，使用 Quart 和 Hypercorn 实现。相比 WSGI 版本，ASGI 版本支持异步处理请求，可以更高效地处理并发请求，尤其是在涉及 I/O 操作（如数据库访问、网络请求等）时性能更好。
同时实现了远端 Bot Bridge 的接口，使得外部系统（如 Telegram Bot）可以通过 HTTP API 调用 AutoPCR 的功能。接口包括获取用户信息、执行日常任务、获取日常记录等，使用 Bearer Token 进行简单的认证。
"""
import asyncio
import os
import traceback
import datetime
import gc
import time
import json
import tracemalloc

from collections import Counter, deque
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Awaitable, Callable
from urllib.parse import quote
from uuid import uuid4
from quart import request as quart_request, jsonify, Response, send_file # type: ignore

from autopcr.module.accountmgr import instance as usermgr, BATCHINFO, AccountException # type: ignore
from autopcr.core.clientpool import instance as clientpool # type: ignore
from autopcr.util.excel_export import export_excel # type: ignore
from autopcr.http_server.httpserver import HttpServer # type: ignore
from autopcr.constants import CACHE_DIR, CLIENT_POOL_MAX_AGE, SERVER_PORT, SERVER_HOST # type: ignore
from autopcr.db.dbstart import db_start # type: ignore
from autopcr.db.assetmgr import instance as assetmgr # type: ignore
from autopcr.db.dbmgr import instance as dbmgr # type: ignore
from autopcr.db.database import db # type: ignore
from autopcr.module.crons import CRONLOG_PATH, CronLog, eCronOperation, write_cron_log # type: ignore
from autopcr.module.modulebase import ModuleResult, eResultStatus # type: ignore
from autopcr.module.modulemgr import ModuleManager, TaskResult # type: ignore
from autopcr.util.logger import instance as autopcr_logger # type: ignore
from hypercorn.config import Config # type: ignore
from hypercorn.asyncio import serve # type: ignore

import sys
import subprocess
import importlib

def install_and_import(package_name, import_name=None):
    """
    检查库是否存在，如果不存在则在运行时自动安装并导入。
    :param package_name: pip 安装时的包名 (例如: 'beautifulsoup4')
    :param import_name: 代码中 import 时的模块名 (例如: 'bs4'，如果不填则默认与 package_name 相同)
    """
    if import_name is None:
        import_name = package_name

    try:
        # 尝试直接导入
        return importlib.import_module(import_name)
    except ImportError:
        print(f"[提示] 未找到模块 {import_name}，正在尝试运行时安装...")
        
        # sys.executable 获取当前运行的 Python 路径，确保安装到正确的虚拟环境/环境中
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        
        print(f"[提示] {package_name} 安装成功，正在导入...")
        return importlib.import_module(import_name)

try:
    import psutil # type: ignore
except Exception:
    psutil = install_and_import("psutil")

_BACKGROUND_TASKS: dict[str, asyncio.Task] = {}
_CRON_ACCOUNT_TIMEOUT_SECONDS = 3600
_CRON_LOG_MAX_BYTES = 4 * 1024 * 1024
_CRON_LOG_KEEP_LINES = 5000
_JOB_TIMEOUT_SECONDS = 3600
_JOB_RESULT_TTL_SECONDS = 120
_JOB_MAX_CONCURRENCY = 2
_MAX_JOB_RESULT_MEMORY_BYTES = 8 * 1024 * 1024
_JOB_RESULT_DIR = os.path.join(CACHE_DIR, "http_server", "job_results")
_MEMORY_LOG_INTERVAL_SECONDS = 60
_MEMORY_ENABLE_TRACEMALLOC = os.getenv("AUTOPCR_ENABLE_TRACEMALLOC") == "1"
_MEMORY_TRACEBACK_LIMIT = 5
_MEMORY_TRACE_TOP_EVERY = 30
_MEMORY_TRACE_TOP_LIMIT = 30
_MEMORY_OBJECT_TYPE_TOP_LIMIT = 30
_CLIENT_POOL_DETAIL_LIMIT = 10


@dataclass(slots=True)
class StoredHttpResponse:
    body: bytes | None
    status_code: int
    content_type: str | None
    headers: dict[str, str] = field(default_factory=dict)
    file_path: str | None = None
    size: int = 0


@dataclass(slots=True)
class BridgeJob:
    job_id: str
    name: str
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: StoredHttpResponse | None = None
    error: str = ""
    task: asyncio.Task | None = None


_BRIDGE_JOBS: dict[str, BridgeJob] = {}
_BRIDGE_JOB_SEMAPHORE = asyncio.Semaphore(max(_JOB_MAX_CONCURRENCY, 1))


def ensure_background_task(name: str, coro_factory: Callable[[], Awaitable[None]]) -> asyncio.Task:
    task = _BACKGROUND_TASKS.get(name)
    if task and not task.done():
        return task

    task = asyncio.create_task(coro_factory(), name=name)
    _BACKGROUND_TASKS[name] = task

    def on_done(done_task: asyncio.Task):
        if _BACKGROUND_TASKS.get(name) is done_task:
            _BACKGROUND_TASKS.pop(name, None)
        try:
            exc = done_task.exception()
        except asyncio.CancelledError:
            return
        if exc:
            autopcr_logger.error(f"background task {name} stopped unexpectedly: {exc}")

    task.add_done_callback(on_done)
    return task


def _now_iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _job_payload(job: BridgeJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "name": job.name,
        "status": job.status,
        "created_at": _now_iso(job.created_at),
        "updated_at": _now_iso(job.updated_at),
        "error": job.error,
    }


async def _store_http_response(response: Response) -> StoredHttpResponse:
    body = await response.get_data()
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "transfer-encoding"}
    }
    size = len(body)
    if size > _MAX_JOB_RESULT_MEMORY_BYTES:
        os.makedirs(_JOB_RESULT_DIR, exist_ok=True)
        file_path = os.path.join(_JOB_RESULT_DIR, f"{uuid4().hex}.bin")
        with open(file_path, "wb") as f:
            f.write(body)
        body = None
        gc.collect()
        return StoredHttpResponse(
            body=None,
            status_code=response.status_code,
            content_type=response.content_type,
            headers=headers,
            file_path=file_path,
            size=size,
        )

    return StoredHttpResponse(
        body=body,
        status_code=response.status_code,
        content_type=response.content_type,
        headers=headers,
        size=size,
    )


def _response_from_stored(stored: StoredHttpResponse) -> Response:
    body = stored.body
    if body is None and stored.file_path:
        with open(stored.file_path, "rb") as f:
            body = f.read()
    response = Response(
        body or b"",
        status=stored.status_code,
        content_type=stored.content_type,
    )
    for key, value in stored.headers.items():
        response.headers[key] = value
    return response


def _delete_stored_response(stored: StoredHttpResponse | None):
    if not stored or not stored.file_path:
        return
    try:
        if os.path.exists(stored.file_path):
            os.remove(stored.file_path)
    except Exception:
        traceback.print_exc()


def _cleanup_orphan_job_result_files(now: float):
    if not os.path.isdir(_JOB_RESULT_DIR):
        return
    try:
        for name in os.listdir(_JOB_RESULT_DIR):
            path = os.path.join(_JOB_RESULT_DIR, name)
            if not os.path.isfile(path):
                continue
            if now - os.path.getmtime(path) > _JOB_RESULT_TTL_SECONDS:
                os.remove(path)
    except Exception:
        traceback.print_exc()


async def _run_bridge_job(job: BridgeJob, work: Callable[[], Awaitable[Response]]):
    job.status = "queued"
    job.updated_at = time.time()
    try:
        async with _BRIDGE_JOB_SEMAPHORE:
            job.status = "running"
            job.updated_at = time.time()
            response = await asyncio.wait_for(work(), timeout=max(_JOB_TIMEOUT_SECONDS, 1))
            job.result = await _store_http_response(response)
            job.status = "finished"
            job.updated_at = time.time()
    except asyncio.TimeoutError:
        job.error = f"job timeout after {_JOB_TIMEOUT_SECONDS}s"
        job.status = "timeout"
        job.updated_at = time.time()
        autopcr_logger.warning(f"bridge job {job.job_id} {job.name}: {job.error}")
    except Exception as e:
        job.error = str(e)
        job.status = "failed"
        job.updated_at = time.time()
        autopcr_logger.exception(f"bridge job {job.job_id} {job.name} failed: {e}")
    finally:
        job.task = None
        gc.collect()


def submit_bridge_job(name: str, work: Callable[[], Awaitable[Response]]):
    job_id = uuid4().hex
    job = BridgeJob(job_id=job_id, name=name)
    _BRIDGE_JOBS[job_id] = job
    job.task = asyncio.create_task(_run_bridge_job(job, work), name=f"autopcr_bridge_job_{job_id}")
    return jsonify(_job_payload(job)), 202


async def bridge_job_cleanup_loop():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for job_id, job in list(_BRIDGE_JOBS.items()):
            task = job.task
            if job.status in {"finished", "failed", "timeout"} and now - job.updated_at > _JOB_RESULT_TTL_SECONDS:
                if task and not task.done():
                    task.cancel()
                _delete_stored_response(job.result)
                job.result = None
                _BRIDGE_JOBS.pop(job_id, None)
        _cleanup_orphan_job_result_files(now)
        gc.collect()


def ensure_tracemalloc_started():
    if not _MEMORY_ENABLE_TRACEMALLOC:
        return False
    if not tracemalloc.is_tracing():
        tracemalloc.start(_MEMORY_TRACEBACK_LIMIT)
    return True


def _format_sema_status(status) -> str:
    try:
        running, waiting, max_count = status
        return f"{running}/{max_count} running, {waiting} waiting"
    except Exception:
        return str(status)


def _format_bytes(size: int | float) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"


def _format_age(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minute}m{sec}s"
    if minute:
        return f"{minute}m{sec}s"
    return f"{sec}s"


def _file_info(path: str) -> tuple[int, str]:
    if not os.path.exists(path):
        return 0, "missing"
    size = os.path.getsize(path)
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
    return size, mtime


def _job_result_dir_status() -> tuple[int, int]:
    if not os.path.isdir(_JOB_RESULT_DIR):
        return 0, 0
    count = 0
    total = 0
    for name in os.listdir(_JOB_RESULT_DIR):
        path = os.path.join(_JOB_RESULT_DIR, name)
        if os.path.isfile(path):
            count += 1
            total += os.path.getsize(path)
    return count, total


def _client_pool_status_lines(limit: int = _CLIENT_POOL_DETAIL_LIMIT) -> list[str]:
    pool = getattr(clientpool, "_pool", {})
    active_uids = getattr(clientpool, "active_uids", {})
    lines = [f"clientpool cached clients: {len(pool)}, active_uids={len(active_uids)}"]
    now = int(time.time())
    for index, (key, client) in enumerate(list(pool.items())[:limit], start=1):
        try:
            sdk_name = key[1] if isinstance(key, tuple) and len(key) > 1 else type(getattr(client, "session", None)).__name__
            uid = getattr(client, "uid", None)
            last_access = getattr(client, "last_access", 0)
            age = _format_age(now - last_access) if last_access else "unknown"
            data = getattr(client, "data", None)
            data_ready = getattr(data, "ready", "unknown")
            logged = getattr(client, "logged", "unknown")
            lines.append(
                f"clientpool cached #{index}: sdk={sdk_name} uid={uid} "
                f"logged={logged} data_ready={data_ready} idle={age}"
            )
        except Exception as e:
            lines.append(f"clientpool cached #{index}: unavailable ({e})")
    if len(pool) > limit:
        lines.append(f"clientpool cached: ... {len(pool) - limit} more")
    return lines


def _object_type_top_lines(limit: int = _MEMORY_OBJECT_TYPE_TOP_LIMIT) -> list[str]:
    try:
        type_counts = Counter(type(obj) for obj in gc.get_objects())
        lines = []
        for obj_type, count in type_counts.most_common(limit):
            module = getattr(obj_type, "__module__", "")
            qualname = getattr(obj_type, "__qualname__", getattr(obj_type, "__name__", str(obj_type)))
            name = f"{module}.{qualname}" if module else qualname
            lines.append(f"{name}: count={count}")
        return lines
    finally:
        try:
            del type_counts
        except UnboundLocalError:
            pass


def runtime_status_lines() -> list[str]:
    lines = []
    now = time.time()

    if psutil:
        try:
            rss = psutil.Process(os.getpid()).memory_info().rss
            lines.append(f"RSS: {_format_bytes(rss)}")
        except Exception as e:
            lines.append(f"RSS: unavailable ({e})")
    else:
        lines.append("RSS: unavailable (psutil not installed)")

    ensure_tracemalloc_started()
    if tracemalloc.is_tracing():
        current, peak = tracemalloc.get_traced_memory()
        lines.append(f"tracemalloc: current={_format_bytes(current)} peak={_format_bytes(peak)}")
    else:
        lines.append("tracemalloc: disabled")

    lines.append(f"objects: {len(gc.get_objects())}")
    lines.append(f"gc count: {gc.get_count()}")

    try:
        cached_props = db.cached_props()
        cache_idle = time.monotonic() - getattr(db, "_cache_last_access", time.monotonic())
        cleanup_task = getattr(db, "_cache_cleanup_task", None)
        if cleanup_task is None:
            cleanup_state = "none"
        elif cleanup_task.done():
            cleanup_state = "done"
        else:
            cleanup_state = "running"
        lines.append(
            "db cache: "
            f"active={getattr(db, '_cache_active_tasks', 'unknown')} "
            f"cached={len(cached_props)} "
            f"idle={_format_age(cache_idle)} "
            f"cleanup={cleanup_state}"
        )
        if cached_props:
            lines.append(f"db cached props: {', '.join(cached_props[:20])}")
    except Exception as e:
        lines.append(f"db cache: unavailable ({e})")

    sema, farm_sema = clientpool.sema_status()
    lines.append(f"clientpool: {_format_sema_status(sema)}")
    lines.append(f"farm pool: {_format_sema_status(farm_sema)}")
    lines.extend(_client_pool_status_lines())

    job_status = Counter(job.status for job in _BRIDGE_JOBS.values())
    oldest_job_age = 0.0
    if _BRIDGE_JOBS:
        oldest_job_age = max(now - job.created_at for job in _BRIDGE_JOBS.values())
    lines.append(f"bridge jobs: total={len(_BRIDGE_JOBS)} status={dict(job_status)} oldest={_format_age(oldest_job_age)}")

    result_count, result_size = _job_result_dir_status()
    lines.append(f"job result files: {result_count} files, {_format_bytes(result_size)}")

    for name in sorted(_BACKGROUND_TASKS):
        task = _BACKGROUND_TASKS[name]
        state = "done" if task.done() else "running"
        lines.append(f"task {name}: {state}")

    cron_size, cron_mtime = _file_info(CRONLOG_PATH)
    lines.append(f"cron log: {_format_bytes(cron_size)}, mtime={cron_mtime}")
    lines.append(f"cron result TTL: {_JOB_RESULT_TTL_SECONDS}s")

    if tracemalloc.is_tracing():
        lines.append("tracemalloc top allocations:")
        lines.extend(_tracemalloc_top_lines(_MEMORY_TRACE_TOP_LIMIT))

    lines.append("gc object type top:")
    lines.extend(_object_type_top_lines(_MEMORY_OBJECT_TYPE_TOP_LIMIT))
    return lines


def _tracemalloc_top_lines(limit: int) -> list[str]:
    if not ensure_tracemalloc_started():
        return []
    snapshot = tracemalloc.take_snapshot()
    try:
        lines = []
        for stat in snapshot.statistics("lineno")[:limit]:
            frame = stat.traceback[0]
            lines.append(
                f"{frame.filename}:{frame.lineno} "
                f"size={stat.size / 1024 / 1024:.1f}MB count={stat.count}"
            )
        return lines
    finally:
        del snapshot


async def memory_logger_loop():
    trace_enabled = ensure_tracemalloc_started()
    proc = psutil.Process(os.getpid()) if psutil else None
    if proc is None:
        autopcr_logger.warning("psutil is not installed; memory logger will omit RSS")
    if not trace_enabled:
        autopcr_logger.warning("tracemalloc is disabled; set AUTOPCR_ENABLE_TRACEMALLOC=1 to enable allocation traces")

    tick = 0
    while True:
        try:
            rss_text = "n/a"
            if proc is not None:
                rss_text = f"{proc.memory_info().rss / 1024 / 1024:.1f}MB"

            traced_text = "disabled"
            peak_text = "disabled"
            if tracemalloc.is_tracing():
                current, peak = tracemalloc.get_traced_memory()
                traced_text = f"{current / 1024 / 1024:.1f}MB"
                peak_text = f"{peak / 1024 / 1024:.1f}MB"
            sema, farm_sema = clientpool.sema_status()
            job_status = Counter(job.status for job in _BRIDGE_JOBS.values())
            autopcr_logger.warning(
                "memory RSS=%s traced=%s peak=%s objects=%s gc=%s jobs=%s clientpool=%s farm=%s",
                rss_text,
                traced_text,
                peak_text,
                len(gc.get_objects()),
                gc.get_count(),
                dict(job_status),
                _format_sema_status(sema),
                _format_sema_status(farm_sema),
            )

            tick += 1
            if tracemalloc.is_tracing() and tick % _MEMORY_TRACE_TOP_EVERY == 0:
                lines = _tracemalloc_top_lines(_MEMORY_TRACE_TOP_LIMIT)
                if lines:
                    autopcr_logger.warning("tracemalloc top allocations:\n%s", "\n".join(lines))
                    gc.collect()
        except Exception as e:
            autopcr_logger.exception(f"memory logger failed: {e}")

        await asyncio.sleep(_MEMORY_LOG_INTERVAL_SECONDS)


def install_runtime_memory_guards():
    """Patch upstream runtime edges that otherwise keep memory after failures."""

    if not getattr(ModuleManager.do_task, "_bot_bridge_guarded", False):
        async def guarded_do_task(self, config: dict, modules: list, isAdminCall: bool = False) -> TaskResult:
            await db.enter_cache_scope()
            try:
                if db.is_clan_battle_time() and self.is_clan_battle_forbidden() and not isAdminCall:
                    key = 'clan_battle' if not modules else modules[0].key
                    return TaskResult(
                        order=[key],
                        result={
                            key: ModuleResult(
                                status=eResultStatus.PANIC,
                                log="会战期间禁止执行任务"
                            )
                        }
                    )

                client = self.client
                activated = False
                await client.activate()
                activated = True
                try:
                    self.config["stamina_relative_not_run"] = any(
                        db.is_campaign(campaign)
                        for campaign in self.config.get("stamina_relative_not_run_campaign_before_one_day", [])
                    )
                    self.config.update(config)

                    resp = TaskResult(order=[], result={})
                    for module in modules:
                        resp.order.append(module.key)
                        resp.result[module.key] = await module.do_from(client)
                        if resp.result[module.key].status == eResultStatus.PANIC:
                            break
                    return resp
                finally:
                    if activated:
                        try:
                            client.deactivate()
                        except Exception:
                            traceback.print_exc()
            finally:
                await db.exit_cache_scope()

        guarded_do_task._bot_bridge_guarded = True
        ModuleManager.do_task = guarded_do_task
        autopcr_logger.warning("installed runtime memory guard: ModuleManager.do_task")

    if not getattr(assetmgr.db, "_bot_bridge_guarded", False):
        async def guarded_asset_db():
            import UnityPy # type: ignore

            payload = None
            bundle = None
            asset = None
            try:
                UnityPy.config.FALLBACK_UNITY_VERSION = "2021.3.20f1"
                payload = await assetmgr.download('a/masterdata_master.unity3d')
                bundle = UnityPy.load(payload)
                payload = None
                asset = bundle.objects[0].read()
                return asset.script
            finally:
                payload = None
                asset = None
                bundle = None
                gc.collect()

        guarded_asset_db._bot_bridge_guarded = True
        assetmgr.db = guarded_asset_db
        autopcr_logger.warning("installed runtime memory guard: assetmgr.db")

    if not getattr(dbmgr.update_db, "_bot_bridge_guarded", False):
        original_update_db = dbmgr.update_db

        async def guarded_update_db(mgr):
            old_engine = getattr(dbmgr, "_engine", None)
            if old_engine is not None:
                try:
                    old_engine.dispose()
                except Exception:
                    traceback.print_exc()
            try:
                return await original_update_db(mgr)
            finally:
                try:
                    gc.collect()
                except Exception:
                    traceback.print_exc()

        guarded_update_db._bot_bridge_guarded = True
        dbmgr.update_db = guarded_update_db
        autopcr_logger.warning("installed runtime memory guard: dbmgr.update_db")


async def trim_client_pool_loop():
    interval = int(os.getenv("AUTOPCR_CLIENT_POOL_TRIM_INTERVAL", "300"))
    max_idle = int(os.getenv("AUTOPCR_CLIENT_POOL_MAX_IDLE_SECONDS", str(CLIENT_POOL_MAX_AGE)))
    while True:
        await asyncio.sleep(max(interval, 30))
        now = int(time.time())
        pool = getattr(clientpool, "_pool", {})
        removed = 0
        for key, client in list(pool.items()):
            if client.last_access + max_idle < now:
                pool.pop(key, None)
                removed += 1
        if removed:
            gc.collect()
        rotate_cron_log_if_needed()


def rotate_cron_log_if_needed():
    if not os.path.exists(CRONLOG_PATH):
        return
    try:
        if os.path.getsize(CRONLOG_PATH) <= _CRON_LOG_MAX_BYTES:
            return
        tail_lines = deque(maxlen=_CRON_LOG_KEEP_LINES)
        with open(CRONLOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                tail_lines.append(line)
        tmp_path = CRONLOG_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(tail_lines)
        os.replace(tmp_path, CRONLOG_PATH)
        gc.collect()
    except Exception:
        traceback.print_exc()


def iter_cron_logs():
    if not os.path.exists(CRONLOG_PATH):
        return
    with open(CRONLOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield CronLog.from_json(line)
            except Exception:
                traceback.print_exc()


async def guarded_cron_account(accountmgr, account: str, scheduled_at: datetime.datetime):
    async with accountmgr.load(account) as mgr:
        await mgr.pre_cron_run(scheduled_at.hour, scheduled_at.minute)
        await write_cron_log(eCronOperation.START, scheduled_at, accountmgr.qid, account, eResultStatus.SUCCESS)
        result_info = await mgr.do_daily()
        await write_cron_log(
            eCronOperation.FINISH,
            datetime.datetime.now(),
            accountmgr.qid,
            account,
            result_info.status,
        )


async def guarded_cron_tick(scheduled_at: datetime.datetime):
    autopcr_logger.info(f"doing guarded cron check in {scheduled_at.hour} {scheduled_at.minute}")
    try:
        for qid in list(usermgr.qids()):
            try:
                async with usermgr.load(qid, readonly=True) as accountmgr:
                    accounts_to_run = []
                    for account in accountmgr.accounts():
                        async with accountmgr.load(account, readonly=True) as mgr:
                            if await mgr.is_cron_run(scheduled_at.hour, scheduled_at.minute):
                                accounts_to_run.append(account)

                    for account in accounts_to_run:
                        try:
                            await asyncio.wait_for(
                                guarded_cron_account(accountmgr, account, scheduled_at),
                                timeout=_CRON_ACCOUNT_TIMEOUT_SECONDS,
                            )
                        except asyncio.TimeoutError:
                            msg = f"cron job timeout after {_CRON_ACCOUNT_TIMEOUT_SECONDS}s"
                            autopcr_logger.warning(f"{qid} {account}: {msg}")
                            await write_cron_log(
                                eCronOperation.FINISH,
                                datetime.datetime.now(),
                                qid,
                                account,
                                eResultStatus.ERROR,
                                msg,
                            )
                        except Exception as e:
                            autopcr_logger.exception(f"error in cron job {qid} {account}: {e}")
                            await write_cron_log(
                                eCronOperation.FINISH,
                                datetime.datetime.now(),
                                qid,
                                account,
                                eResultStatus.ERROR,
                                str(e),
                            )
                        finally:
                            gc.collect()
            except Exception as e:
                autopcr_logger.exception(f"error while scanning cron jobs for {qid}: {e}")
    finally:
        rotate_cron_log_if_needed()
        gc.collect()


async def guarded_cron_loop():
    running_tick: asyncio.Task | None = None
    last_minute = datetime.datetime.now().replace(second=0, microsecond=0) - datetime.timedelta(minutes=1)
    while True:
        await asyncio.sleep(30)
        if running_tick and running_tick.done():
            try:
                running_tick.result()
            except Exception as e:
                autopcr_logger.exception(f"guarded cron tick failed: {e}")
            running_tick = None
        current_minute = datetime.datetime.now().replace(second=0, microsecond=0)
        if current_minute == last_minute:
            continue
        last_minute = current_minute
        if running_tick and not running_tick.done():
            autopcr_logger.warning(
                f"skip cron tick {current_minute:%Y-%m-%d %H:%M}: previous tick is still running"
            )
            continue
        running_tick = asyncio.create_task(guarded_cron_tick(current_minute))


def queue_guarded_crons():
    ensure_background_task("autopcr_guarded_cron", guarded_cron_loop)

def install_bot_bridge(server: HttpServer):
    bot_token = os.getenv("AUTOPCR_BOT_TOKEN") or os.getenv("autopcr_bot_token") or ""

    def require_bot_token(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not bot_token:
                return json_response({"message": "AUTOPCR_BOT_TOKEN 未配置，bot bridge 未启用"}, status=503)
            auth = quart_request.headers.get("Authorization", "")
            if auth != f"Bearer {bot_token}":
                return json_response({"message": "unauthorized"}, status=401)
            return await func(*args, **kwargs)
        return wrapper

    def json_response(payload: Any, status: int = 200) -> Response:
        return Response(
            json.dumps(payload, ensure_ascii=False),
            status=status,
            content_type="application/json",
        )

    def text_msg(text: str):
        return json_response({"messages": [{"type": "text", "text": text}]})

    def lines_msg(lines: list[str]):
        return json_response({"messages": [{"type": "lines", "lines": [str(line) for line in lines]}]})

    def table_msg(header: list[str], rows: list[list[str]]):
        return json_response({
            "messages": [{
                "type": "table",
                "header": [str(item) for item in header],
                "rows": [[str(cell) for cell in row] for row in rows],
            }]
        })

    def result_ref_msg(ref: dict[str, Any]):
        return json_response({"messages": [{"type": "autopcr_result_ref", "ref": ref}]})

    def daily_all_refs_msg(refs: list[dict[str, Any]]):
        return json_response({"messages": [{"type": "autopcr_daily_all_refs", "refs": refs}]})

    def result_raw_path(qid: str, account: str, result_type: str, key: str, tool_key: str | None = None) -> str:
        account_part = quote(account, safe="")
        key_part = quote(key, safe="")
        if result_type == "single_result":
            tool_part = quote(tool_key or "", safe="")
            return f"bot/users/{qid}/accounts/{account_part}/results/single/{tool_part}/{key_part}/raw"
        return f"bot/users/{qid}/accounts/{account_part}/results/daily/{key_part}/raw"

    def result_info_ref(qid: str, account: str, result_info, result_type: str, tool_key: str | None = None) -> dict[str, Any]:
        key = str(result_info.key)
        return {
            "qid": str(qid),
            "account": str(account),
            "alias": str(getattr(result_info, "alias", account) or account),
            "key": key,
            "time": str(getattr(result_info, "time", "") or ""),
            "status": str(getattr(getattr(result_info, "status", None), "value", getattr(result_info, "status", ""))),
            "result_type": result_type,
            "tool_key": str(tool_key or ""),
            "raw_path": result_raw_path(qid, account, result_type, key, tool_key),
        }

    def find_daily_result_info(account, key: str):
        for item in account.get_daily_result_list():
            if str(item.key) == str(key):
                return item
        return None

    def find_single_result_info(account, tool_key: str, key: str):
        for item in account.get_single_result_list(tool_key):
            if str(item.key) == str(key):
                return item
        return None

    async def result_file_response(result_info):
        path = getattr(result_info, "path", "")
        if not path or not os.path.exists(path):
            return json_response({"message": "result file not found"}, status=404)
        return await send_file(path, mimetype="application/json")

    def cron_log_filters(args: list[str]):
        status_filters = []
        target_date = None
        cur = datetime.datetime.now()
        if has_arg(args, "错误"):
            status_filters.append(eResultStatus.ERROR)
        if has_arg(args, "警告"):
            status_filters.append(eResultStatus.WARNING)
        if has_arg(args, "成功"):
            status_filters.append(eResultStatus.SUCCESS)
        if has_arg(args, "昨日"):
            cur -= datetime.timedelta(days=1)
            target_date = cur.date()
        if has_arg(args, "今日"):
            target_date = cur.date()
        return status_filters, target_date

    def cron_log_matches(log: CronLog, status_filters: list[eResultStatus], target_date) -> bool:
        if status_filters and log.status not in status_filters:
            return False
        if target_date and log.time.date() != target_date:
            return False
        return True

    def select_cron_log_lines(args: list[str]) -> list[str]:
        status_filters, target_date = cron_log_filters(args)
        recent_logs = deque(maxlen=40)
        for log in iter_cron_logs():
            if cron_log_matches(log, status_filters, target_date):
                recent_logs.append(log)
        return [str(log) for log in reversed(recent_logs)]

    def summarize_cron_status(args: list[str]):
        cur = datetime.datetime.now()
        target_label = "今日"
        if has_arg(args, "昨日"):
            cur -= datetime.timedelta(days=1)
            target_label = "昨日"
        target_date = cur.date()
        start_count = 0
        finish_count = 0
        status = Counter()
        for log in iter_cron_logs():
            if log.time.date() != target_date:
                continue
            if log.operation == eCronOperation.START:
                start_count += 1
            if log.operation == eCronOperation.FINISH:
                finish_count += 1
                status[log.status] += 1
        return target_label, start_count, finish_count, status

    def has_arg(args: list[str], key: str) -> bool:
        if key in args:
            args.remove(key)
            return True
        return False

    def visible_user_ids_from_context(context: dict) -> set[str]:
        visible = context.get("visible_user_ids") or []
        return {str(user_id) for user_id in visible if str(user_id).isdigit()}

    def find_ghost_qids(context: dict) -> list[str] | None:
        visible = visible_user_ids_from_context(context)
        if not visible:
            return None
        return sorted(qid for qid in usermgr.qids() if qid.isdigit() and qid not in visible)

    def normalize_account(acc: str | None):
        if acc == "所有":
            return BATCHINFO, True
        if acc == "批量":
            return BATCHINFO, False
        if not acc or acc == "_default":
            return "_default", False
        return acc, False

    def resolve_account_name(mgr, account_name: str):
        if account_name != "_default":
            return account_name
        if mgr.default_account:
            return mgr.default_account
        accounts = list(mgr.accounts())
        if len(accounts) == 1:
            return accounts[0]
        raise AccountException("No default account")

    async def get_context():
        data = await quart_request.get_json(silent=True) or {}
        return data.get("context") or {}

    async def execute_daily_all(qid: str, context: dict[str, Any]) -> Response:
        is_admin = bool(context.get("is_admin"))

        async with usermgr.load(qid, readonly=True) as mgr:
            aliases = list(mgr.accounts())
            if not aliases:
                return text_msg("未找到可执行的账号")

            refs = []
            for alias in aliases:
                try:
                    async with mgr.load(alias) as acc:
                        result_info = await acc.do_daily(is_admin)
                        refs.append(result_info_ref(qid, alias, result_info, "daily_result"))
                except Exception as e:
                    traceback.print_exc()
                    refs.append({
                        "qid": str(qid),
                        "account": str(alias),
                        "alias": str(alias),
                        "status": eResultStatus.ERROR.value,
                        "error": str(e),
                    })

            return daily_all_refs_msg(refs)

    async def execute_daily(qid: str, acc: str, context: dict[str, Any]) -> Response:
        is_admin = bool(context.get("is_admin"))
        account_name, force_all = normalize_account(acc)

        async with usermgr.load(qid, readonly=True) as mgr:
            account_name = resolve_account_name(mgr, account_name)
            async with mgr.load(account_name, force_use_all=force_all) as account:
                result_info = await account.do_daily(is_admin)
                return result_ref_msg(result_info_ref(qid, account_name, result_info, "daily_result"))

    async def execute_tool(qid: str, acc: str, tool_key: str, data: dict[str, Any]) -> Response:
        module_config = data.get("config") or {}
        export = bool(data.get("export"))
        context = data.get("context") or {}
        is_admin = bool(context.get("is_admin"))

        account_name, force_all = normalize_account(acc)
        async with usermgr.load(qid, readonly=True) as mgr:
            account_name = resolve_account_name(mgr, account_name)
            async with mgr.load(account_name, force_use_all=force_all) as account:
                result_info = await account.do_from_key(module_config, tool_key, is_admin)

                if isinstance(result_info, list):
                    if not result_info:
                        return text_msg("未选择账号！请到网页端批量运行选择账号后运行")
                    result_info = result_info[0]

                if export:
                    result = result_info.get_result()
                    xlsx = None
                    try:
                        xlsx = await export_excel(result.table)
                        filename = f"{data.get('tool_name') or tool_key}_{account.alias}_{db.format_time_safe(datetime.datetime.now())}.xlsx"
                        content = xlsx.getvalue()
                        response = Response(
                            content,
                            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                        )
                        return response
                    finally:
                        if xlsx is not None:
                            xlsx.close()
                        result = None
                        result_info = None
                        gc.collect()

                return result_ref_msg(result_info_ref(qid, account_name, result_info, "single_result", tool_key))

    @server.api.route("/bot/health", methods=["GET"])
    @require_bot_token
    async def bot_health():
        return jsonify({"status": "ok"})

    @server.api.route("/bot/jobs/<string:job_id>", methods=["GET"])
    @require_bot_token
    async def bot_job_status(job_id: str):
        job = _BRIDGE_JOBS.get(job_id)
        if not job:
            return jsonify({"message": "job not found"}), 404
        return jsonify(_job_payload(job))

    @server.api.route("/bot/jobs/<string:job_id>/result", methods=["GET"])
    @require_bot_token
    async def bot_job_result(job_id: str):
        job = _BRIDGE_JOBS.get(job_id)
        if not job:
            return jsonify({"message": "job not found"}), 404
        if job.status in {"queued", "running"}:
            return jsonify(_job_payload(job)), 202
        if job.status == "timeout":
            return jsonify(_job_payload(job)), 504
        if job.status == "failed":
            return jsonify(_job_payload(job)), 500
        if job.result is None:
            _BRIDGE_JOBS.pop(job_id, None)
            return jsonify({"message": "job result already consumed or expired", **_job_payload(job)}), 410

        stored = job.result
        job.result = None
        _BRIDGE_JOBS.pop(job_id, None)
        try:
            response = _response_from_stored(stored)
            return response
        finally:
            _delete_stored_response(stored)
            gc.collect()

    @server.api.route("/bot/users/<string:qid>", methods=["GET"])
    @require_bot_token
    async def bot_user_info(qid: str):
        if qid not in set(usermgr.qids()):
            return jsonify({"message": f"未找到{qid}的账号，请发送【#配置日常】进行配置"}), 404

        async with usermgr.load(qid, readonly=True) as mgr:
            accounts = []
            for alias in mgr.accounts():
                async with mgr.load(alias, readonly=True) as acc:
                    item = acc.generate_result_info()
                    item["alias"] = alias
                    accounts.append(item)

            return jsonify({
                "qq": qid,
                "default_account": mgr.default_account,
                "accounts": accounts,
                "clan": mgr.secret.clan,
            })

    @server.api.route("/bot/runtime/status", methods=["GET"])
    @require_bot_token
    async def bot_runtime_status():
        return lines_msg(runtime_status_lines())

    @server.api.route("/bot/gacha/current", methods=["GET"])
    @require_bot_token
    async def bot_gacha_current():
        return text_msg("\n".join(db.get_mirai_gacha()))

    @server.api.route("/bot/users/<string:qid>/daily", methods=["POST"])
    @require_bot_token
    async def bot_daily_all(qid: str):
        data = await quart_request.get_json(silent=True) or {}
        context = data.get("context") or {}
        if data.get("async"):
            return submit_bridge_job(f"daily_all:{qid}", lambda: execute_daily_all(qid, context))
        return await execute_daily_all(qid, context)

    @server.api.route("/bot/users/<string:qid>/accounts/<string:acc>/daily", methods=["POST"])
    @require_bot_token
    async def bot_daily(qid: str, acc: str):
        data = await quart_request.get_json(silent=True) or {}
        context = data.get("context") or {}
        if data.get("async"):
            return submit_bridge_job(f"daily:{qid}:{acc}", lambda: execute_daily(qid, acc, context))
        return await execute_daily(qid, acc, context)

    @server.api.route("/bot/users/<string:qid>/daily-records", methods=["GET"])
    @require_bot_token
    async def bot_daily_records(qid: str):
        rows = []
        async with usermgr.load(qid, readonly=True) as mgr:
            for alias in mgr.accounts():
                async with mgr.load(alias, readonly=True) as acc:
                    rows.extend([
                        [acc.alias, item.time, "#" + item.status.value]
                        for item in acc.get_daily_result_list()
                    ])

        if not rows:
            return text_msg("暂无日常记录")

        return table_msg(["昵称", "清日常时间", "状态"], rows)

    @server.api.route("/bot/users/<string:qid>/accounts/<string:acc>/daily-results/<int:result_id>", methods=["GET"])
    @require_bot_token
    async def bot_daily_report(qid: str, acc: str, result_id: int):
        account_name, force_all = normalize_account(acc)
        async with usermgr.load(qid, readonly=True) as mgr:
            account_name = resolve_account_name(mgr, account_name)
            async with mgr.load(account_name, readonly=True, force_use_all=force_all) as account:
                results = account.get_daily_result_list()
                if result_id < 0 or result_id >= len(results):
                    return text_msg("未找到日常报告")
                return result_ref_msg(result_info_ref(qid, account_name, results[result_id], "daily_result"))

    @server.api.route("/bot/users/<string:qid>/accounts/<string:acc>/results/daily/<string:key>/raw", methods=["GET"])
    @require_bot_token
    async def bot_daily_result_raw(qid: str, acc: str, key: str):
        account_name, force_all = normalize_account(acc)
        async with usermgr.load(qid, readonly=True) as mgr:
            account_name = resolve_account_name(mgr, account_name)
            async with mgr.load(account_name, readonly=True, force_use_all=force_all) as account:
                result_info = find_daily_result_info(account, key)
                if not result_info:
                    return json_response({"message": "result not found"}, status=404)
                return await result_file_response(result_info)

    @server.api.route("/bot/users/<string:qid>/accounts/<string:acc>/results/single/<string:tool_key>/<string:key>/raw", methods=["GET"])
    @require_bot_token
    async def bot_single_result_raw(qid: str, acc: str, tool_key: str, key: str):
        account_name, force_all = normalize_account(acc)
        async with usermgr.load(qid, readonly=True) as mgr:
            account_name = resolve_account_name(mgr, account_name)
            async with mgr.load(account_name, readonly=True, force_use_all=force_all) as account:
                result_info = find_single_result_info(account, tool_key, key)
                if not result_info:
                    return json_response({"message": "result not found"}, status=404)
                return await result_file_response(result_info)

    @server.api.route("/bot/users/<string:qid>/accounts/<string:acc>/tools/<string:tool_key>", methods=["POST"])
    @require_bot_token
    async def bot_tool(qid: str, acc: str, tool_key: str):
        data = await quart_request.get_json(silent=True) or {}
        if data.get("async"):
            return submit_bridge_job(f"tool:{qid}:{acc}:{tool_key}", lambda: execute_tool(qid, acc, tool_key, data))
        return await execute_tool(qid, acc, tool_key, data)

    @server.api.route("/bot/users/<string:qid>/commands/<string:command>", methods=["POST"])
    @require_bot_token
    async def bot_command(qid: str, command: str):
        data = await quart_request.get_json(silent=True) or {}
        args = [str(arg) for arg in data.get("args") or []]
        context = data.get("context") or {}

        if command == "cron_log":
            lines = select_cron_log_lines(args)
            return lines_msg(lines or ["暂无定时日志"])

        if command == "cron_status":
            target_label, start_count, finish_count, status = summarize_cron_status(args)
            lines = [f"{target_label}定时任务：启动{start_count}个，完成{finish_count}个"]
            lines += [f"{key.value}: {value}" for key, value in status.items()]
            return lines_msg(lines)

        if command == "cron_statistic":
            cnt_clanbattle = Counter()
            cnt = Counter()
            for user_qid in usermgr.qids():
                async with usermgr.load(user_qid, readonly=True) as accmgr:
                    for alias in accmgr.accounts():
                        async with accmgr.load(alias, readonly=True) as acc:
                            for i in range(1, 5):
                                suffix = f"cron{i}"
                                if acc.data.config.get(suffix, False):
                                    cron_time = acc.data.config.get(f"time_{suffix}", "00:00")
                                    if cron_time.count(":") == 2:
                                        cron_time = ":".join(cron_time.split(":")[:2])
                                    cnt[cron_time] += 1
                                    if acc.data.config.get(f"clanbattle_run_{suffix}", False):
                                        cnt_clanbattle[cron_time] += 1
            rows = [[key, str(value), str(cnt_clanbattle[key])] for key, value in cnt.items()]
            rows = sorted(rows, key=lambda row: row[0])
            rows.append(["总计", str(sum(cnt.values())), str(sum(cnt_clanbattle.values()))])
            return table_msg(["时间", "定时任务数", "公会战任务数"], rows)

        if command == "clan_forbid":
            lines = ["会战期间仅管理员调用"]
            for user_qid in usermgr.qids():
                async with usermgr.load(user_qid, readonly=True) as accmgr:
                    for alias in accmgr.accounts():
                        async with accmgr.load(alias, readonly=True) as acc:
                            if acc.is_clan_battle_forbidden():
                                lines.append(f"{acc.qq}  {acc.alias} ")
            return lines_msg(lines)

        if command == "find_ghost":
            ghosts = find_ghost_qids(context)
            if ghosts is None:
                return text_msg("缺少可见成员列表，无法判断内鬼")
            return text_msg(" ".join(ghosts) if ghosts else "未找到内鬼")

        if command == "clean_ghost":
            ghosts = find_ghost_qids(context)
            if ghosts is None:
                return text_msg("缺少可见成员列表，无法判断内鬼")
            if not ghosts:
                return text_msg("未找到内鬼")
            deleted = []
            for ghost in ghosts:
                if not ghost.isdigit():
                    continue
                try:
                    usermgr.delete(ghost)
                    deleted.append(ghost)
                except Exception:
                    traceback.print_exc()
            if not deleted:
                return text_msg("未找到可清除的内鬼")
            return text_msg(" ".join([f"已清除{len(deleted)}个内鬼:"] + deleted))

        if command == "group_clan_forbid":
            return text_msg("远端 bridge v1 暂不支持查群禁用，请使用查禁用")

        if command == "ocr_team":
            return text_msg("远端 bridge v1 不支持远端识图")

        return text_msg(f"远端暂未实现 bot command: {command}")

async def main():
    # 原来 httpserver_test.py 的初始化
    install_runtime_memory_guards()
    server = HttpServer(host=SERVER_HOST, port=SERVER_PORT)
    install_bot_bridge(server)
    await db_start()
    queue_guarded_crons()
    ensure_background_task("autopcr_client_pool_trim", trim_client_pool_loop)
    ensure_background_task("autopcr_bridge_job_cleanup", bridge_job_cleanup_loop)
    ensure_background_task("autopcr_memory_logger", memory_logger_loop)
    
    @server.quart.before_request
    async def fix_remote_addr():
        # 优先取 X-Real-IP，其次取 X-Forwarded-For 的第一个
        real_ip = (
            quart_request.headers.get("X-Real-IP") or
            quart_request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        )
        if real_ip:
            quart_request.scope["client"] = (real_ip, 0)

    #server.quart.asgi_app = ProxyFix(
    #    server.quart.asgi_app,
    #    x_for=1,       # 信任 1 层 X-Forwarded-For
    #    x_proto=1,     # 信任 X-Forwarded-Proto
    #    x_host=1,      # 信任 X-Forwarded-Host
    #)    

    @server.quart.route("/health")
    async def health_check():
        return jsonify({
            "status": "ok",
        })

    # 手动执行 run_forever 里的 blueprint 注册（关键！）
    server.quart.register_blueprint(server.app)

    # 配置并启动 Hypercorn
    config = Config()
    config.bind = [f"{SERVER_HOST}:{SERVER_PORT}"]
    config.accesslog = "-"
    config.errorlog  = "-"
    config.trusted_hops = 1
    config.access_log_format = '%({x-real-ip}i)s - %(t)s "%(r)s" %(s)s %(b)s %(D)sµs'

    await serve(server.quart, config)

if __name__ == "__main__":
    asyncio.run(main())
