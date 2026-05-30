"""
ASGI 版本的 HTTP 服务器，使用 Quart 和 Hypercorn 实现。相比 WSGI 版本，ASGI 版本支持异步处理请求，可以更高效地处理并发请求，尤其是在涉及 I/O 操作（如数据库访问、网络请求等）时性能更好。
同时实现了远端 Bot Bridge 的接口，使得外部系统（如 Telegram Bot）可以通过 HTTP API 调用 AutoPCR 的功能。接口包括获取用户信息、执行日常任务、获取日常记录等，使用 Bearer Token 进行简单的认证。
"""
import asyncio
import os
import base64
import traceback

from functools import wraps
from quart import request as quart_request, jsonify, Response # type: ignore

from autopcr.module.accountmgr import instance as usermgr, BATCHINFO # type: ignore
from autopcr.core.clientpool import instance as clientpool # type: ignore
from autopcr.util.draw import instance as drawer # type: ignore
from autopcr.util.excel_export import export_excel # type: ignore
from autopcr.http_server.httpserver import HttpServer # type: ignore
from autopcr.constants import SERVER_PORT, SERVER_HOST # type: ignore
from autopcr.db.dbstart import db_start # type: ignore
from autopcr.db.database import db # type: ignore
from autopcr.module.crons import queue_crons # type: ignore
from hypercorn.config import Config # type: ignore
from hypercorn.asyncio import serve # type: ignore

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

    async def image_msg(img):
        bio = await drawer.img2bytesio(img, "WEBP")
        data = base64.b64encode(bio.getvalue()).decode()
        return jsonify({
            "messages": [{
                "type": "image",
                "content": data,
                "mime_type": "image/webp",
            }]
        })

    def normalize_account(acc: str | None):
        if not acc or acc == "_default":
            return "", False
        if acc == "所有":
            return BATCHINFO, True
        if acc == "批量":
            return BATCHINFO, False
        return acc, False

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

            img = await drawer.draw(["昵称", "清日常结果", "状态"], rows)
            return await image_msg(img)

    @server.api.route("/bot/users/<string:qid>/accounts/<string:acc>/daily", methods=["POST"])
    @require_bot_token
    async def bot_daily(qid: str, acc: str):
        context = await get_context()
        is_admin = bool(context.get("is_admin"))
        account_name, force_all = normalize_account(acc)

        async with usermgr.load(qid, readonly=True) as mgr:
            async with mgr.load(account_name, force_use_all=force_all) as account:
                result_info = await account.do_daily(is_admin)
                img = await drawer.draw_tasks_result(result_info.get_result())
                return await image_msg(img)

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

        img = await drawer.draw(["昵称", "清日常时间", "状态"], rows)
        return await image_msg(img)

    @server.api.route("/bot/users/<string:qid>/accounts/<string:acc>/daily-results/<int:result_id>", methods=["GET"])
    @require_bot_token
    async def bot_daily_report(qid: str, acc: str, result_id: int):
        account_name, force_all = normalize_account(acc)
        async with usermgr.load(qid, readonly=True) as mgr:
            async with mgr.load(account_name, readonly=True, force_use_all=force_all) as account:
                result = await account.get_daily_result_from_id(result_id)
                if not result:
                    return text_msg("未找到日常报告")
                img = await drawer.draw_tasks_result(result)
                return await image_msg(img)

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
            async with mgr.load(account_name, force_use_all=force_all) as account:
                result_info = await account.do_from_key(module_config, tool_key, is_admin)

                if isinstance(result_info, list):
                    if not result_info:
                        return text_msg("未选择账号！请到网页端批量运行选择账号后运行")
                    result_info = result_info[0]

                result = result_info.get_result()

                if export:
                    xlsx = await export_excel(result.table)
                    filename = f"{data.get('tool_name') or tool_key}_{account.alias}_{db.format_time_safe(db.datetime.datetime.now())}.xlsx"
                    return Response(
                        xlsx.getvalue(),
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                    )

                img = await drawer.draw_task_result(result)
                return await image_msg(img)

    @server.api.route("/bot/users/<string:qid>/commands/<string:command>", methods=["POST"])
    @require_bot_token
    async def bot_command(qid: str, command: str):
        return text_msg(f"远端暂未实现 bot command: {command}")

async def main():
    # 原来 httpserver_test.py 的初始化
    server = HttpServer(host=SERVER_HOST, port=SERVER_PORT)
    install_bot_bridge(server)
    queue_crons()
    
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

    # db_start 作为后台任务
    asyncio.get_event_loop().create_task(db_start())

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