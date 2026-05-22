from __future__ import annotations

from fastapi import Query
from fastapi.responses import HTMLResponse
from nonebot import get_driver

from ...integrations.lxns.oauth_client import oa_client
from ...integrations.lxns.use_cases.bind_oauth import bind_by_oauth_code


CALLBACK_PATH = "/lxns/oauth/callback"


def _render_html(title: str, message: str) -> HTMLResponse:
    html = f"""
    <html>
      <head><meta charset="utf-8"><title>{title}</title></head>
      <body>
        <h3>{title}</h3>
        <p>{message}</p>
      </body>
    </html>
    """.strip()
    return HTMLResponse(content=html)


def register_oauth_callback_route() -> None:
    driver = get_driver()
    app = getattr(driver, "server_app", None)
    if app is None:
        return

    @app.get(CALLBACK_PATH)
    async def lxns_oauth_callback(
        code: str | None = Query(default=None),
        state: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ):
        if error:
            if state:
                pending = oa_client.get_wait_bind_user(state)
                if pending:
                    oa_client.mark_bind_result(
                        state=state,
                        user_id_hash=pending["user_id_hash"],
                        status="error",
                        message=error,
                    )
                    oa_client.remove_wait_bind_user(state)
            return _render_html("OAuth 绑定失败", error)

        if not code or not state:
            return _render_html("OAuth 绑定失败", "缺少授权码或 state")

        finished = oa_client.get_bind_result_by_state(state)
        if finished is not None:
            if finished.get("status") == "bound":
                return _render_html("OAuth 绑定成功", "授权已经完成，你可以返回 QQ 使用相关功能。")
            return _render_html("OAuth 绑定失败", str(finished.get("message", "绑定失败")))

        try:
            wait_bind_user = oa_client.validate_wait_bind_user(state)
            result = await bind_by_oauth_code(
                qq=wait_bind_user["user_id_hash"],
                code=code,
                state=state,
            )
        except Exception as exc:  # noqa: BLE001
            return _render_html("OAuth 绑定失败", str(exc))

        if result.status == "bound":
            return _render_html("OAuth 绑定成功", "授权已完成，你现在可以返回 QQ 使用相关功能。")
        return _render_html("OAuth 绑定失败", result.message)