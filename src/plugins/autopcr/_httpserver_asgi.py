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

from collections import Counter
from functools import wraps
from quart import request as quart_request, jsonify, Response # type: ignore

from autopcr.module.accountmgr import instance as usermgr, BATCHINFO, AccountException # type: ignore
from autopcr.core.clientpool import instance as clientpool # type: ignore
from autopcr.util.excel_export import export_excel # type: ignore
from autopcr.http_server.httpserver import HttpServer # type: ignore
from autopcr.constants import CLIENT_POOL_MAX_AGE, SERVER_PORT, SERVER_HOST # type: ignore
from autopcr.db.dbstart import db_start # type: ignore
from autopcr.db.database import db # type: ignore
from autopcr.module.crons import CRONLOG_PATH, CronLog, eCronOperation, queue_crons # type: ignore
from autopcr.module.modulebase import ModuleResult, eResultStatus # type: ignore
from autopcr.module.modulemgr import ModuleManager, TaskResult # type: ignore
from hypercorn.config import Config # type: ignore
from hypercorn.asyncio import serve # type: ignore


def install_runtime_memory_guards():
    """Patch upstream runtime edges that otherwise keep memory after failures."""

    if getattr(ModuleManager.do_task, "_bot_bridge_guarded", False):
        return

    async def guarded_do_task(self, config: dict, modules: list, isAdminCall: bool = False) -> TaskResult:
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

    guarded_do_task._bot_bridge_guarded = True
    ModuleManager.do_task = guarded_do_task


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

def install_bot_bridge(server: HttpServer):
    bot_token = os.getenv("AUTOPCR_BOT_TOKEN") or os.getenv("autopcr_bot_token") or ""

    def require_bot_token(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not bot_token:
                return jsonify({"message": "AUTOPCR_BOT_TOKEN 未配置，bot bridge 未启用"}), 503
            auth = quart_request.headers.get("Authorization", "")
            if auth != f"Bearer {bot_token}":
                return jsonify({"message": "unauthorized"}), 401
            return await func(*args, **kwargs)
        return wrapper

    def text_msg(text: str):
        return jsonify({"messages": [{"type": "text", "text": text}]})

    def lines_msg(lines: list[str]):
        return jsonify({"messages": [{"type": "lines", "lines": [str(line) for line in lines]}]})

    def table_msg(header: list[str], rows: list[list[str]]):
        return jsonify({
            "messages": [{
                "type": "table",
                "header": [str(item) for item in header],
                "rows": [[str(cell) for cell in row] for row in rows],
            }]
        })

    def task_result_msg(result):
        return jsonify({"messages": [{"type": "autopcr_task_result", "result": json.loads(result.to_json())}]})

    def module_result_msg(result):
        return jsonify({"messages": [{"type": "autopcr_module_result", "result": json.loads(result.to_json())}]})

    def load_cron_logs():
        if not os.path.exists(CRONLOG_PATH):
            return []
        logs = []
        with open(CRONLOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    logs.append(CronLog.from_json(line))
                except Exception:
                    traceback.print_exc()
        return logs

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

    @server.api.route("/bot/health", methods=["GET"])
    @require_bot_token
    async def bot_health():
        return jsonify({"status": "ok"})

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
        sema, farm_sema = clientpool.sema_status()
        lines = []
        for i, (running, waiting, max_count) in enumerate([sema, farm_sema]):
            lines.append(f"运行状态{i}：{running}/{max_count}正在运行，{waiting}等待中")
        return text_msg("\n".join(lines))

    @server.api.route("/bot/gacha/current", methods=["GET"])
    @require_bot_token
    async def bot_gacha_current():
        return text_msg("\n".join(db.get_mirai_gacha()))

    @server.api.route("/bot/users/<string:qid>/daily", methods=["POST"])
    @require_bot_token
    async def bot_daily_all(qid: str):
        context = await get_context()
        is_admin = bool(context.get("is_admin"))

        async with usermgr.load(qid, readonly=True) as mgr:
            aliases = list(mgr.accounts())
            if not aliases:
                return text_msg("未找到可执行的账号")

            rows = []
            for alias in aliases:
                try:
                    async with mgr.load(alias) as acc:
                        result_info = await acc.do_daily(is_admin)
                        result = result_info.get_result()
                        rows.append([alias, result.get_last_result().log, "#" + result_info.status.value])
                except Exception as e:
                    traceback.print_exc()
                    rows.append([alias, str(e), "#错误"])

            return table_msg(["昵称", "清日常结果", "状态"], rows)

    @server.api.route("/bot/users/<string:qid>/accounts/<string:acc>/daily", methods=["POST"])
    @require_bot_token
    async def bot_daily(qid: str, acc: str):
        context = await get_context()
        is_admin = bool(context.get("is_admin"))
        account_name, force_all = normalize_account(acc)

        async with usermgr.load(qid, readonly=True) as mgr:
            account_name = resolve_account_name(mgr, account_name)
            async with mgr.load(account_name, force_use_all=force_all) as account:
                result_info = await account.do_daily(is_admin)
                return task_result_msg(result_info.get_result())

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
                result = await account.get_daily_result_from_id(result_id)
                if not result:
                    return text_msg("未找到日常报告")
                return task_result_msg(result)

    @server.api.route("/bot/users/<string:qid>/accounts/<string:acc>/tools/<string:tool_key>", methods=["POST"])
    @require_bot_token
    async def bot_tool(qid: str, acc: str, tool_key: str):
        data = await quart_request.get_json(silent=True) or {}
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

                result = result_info.get_result()

                if export:
                    xlsx = await export_excel(result.table)
                    filename = f"{data.get('tool_name') or tool_key}_{account.alias}_{db.format_time_safe(datetime.datetime.now())}.xlsx"
                    content = xlsx.getvalue()
                    xlsx.close()
                    gc.collect()
                    return Response(
                        content,
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                    )

                return module_result_msg(result)

    @server.api.route("/bot/users/<string:qid>/commands/<string:command>", methods=["POST"])
    @require_bot_token
    async def bot_command(qid: str, command: str):
        data = await quart_request.get_json(silent=True) or {}
        args = [str(arg) for arg in data.get("args") or []]
        context = data.get("context") or {}

        if command == "cron_log":
            logs = load_cron_logs()
            cur = datetime.datetime.now()
            if has_arg(args, "错误"):
                logs = [log for log in logs if log.status == eResultStatus.ERROR]
            if has_arg(args, "警告"):
                logs = [log for log in logs if log.status == eResultStatus.WARNING]
            if has_arg(args, "成功"):
                logs = [log for log in logs if log.status == eResultStatus.SUCCESS]
            if has_arg(args, "昨日"):
                cur -= datetime.timedelta(days=1)
                logs = [log for log in logs if log.time.date() == cur.date()]
            if has_arg(args, "今日"):
                logs = [log for log in logs if log.time.date() == cur.date()]

            lines = [str(log) for log in logs[-40:][::-1]]
            return lines_msg(lines or ["暂无定时日志"])

        if command == "cron_status":
            logs = load_cron_logs()
            cur = datetime.datetime.now()
            target_label = "今日"
            if has_arg(args, "昨日"):
                cur -= datetime.timedelta(days=1)
                target_label = "昨日"
            start_logs = [log for log in logs if log.operation == eCronOperation.START and log.time.date() == cur.date()]
            finish_logs = [log for log in logs if log.operation == eCronOperation.FINISH and log.time.date() == cur.date()]
            status = Counter(log.status for log in finish_logs)
            lines = [f"{target_label}定时任务：启动{len(start_logs)}个，完成{len(finish_logs)}个"]
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
    queue_crons()
    asyncio.get_event_loop().create_task(trim_client_pool_loop())
    
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
