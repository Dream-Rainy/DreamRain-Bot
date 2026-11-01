"""Outbound transport shared by management and the original alias editor."""
import asyncio
from time import monotonic

import httpx
from fastapi import FastAPI
from arcade_helper.web import BASE
from arcade_helper.web.client import EditorSession


class EditorBridge:
    def __init__(self, portal, url, token, *, api_path, base=BASE, page_path=None):
        self.portal, self.url, self.token = portal, url, token
        self.api_path, self.base, self.page_path = api_path, base, page_path
        self.sessions = {}
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        app.include_router(portal.router)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://management.internal")

    async def open(self, *, page_path=None, **identity):
        self.portal.sessions.limit("editor:" + identity["adapter"] + ":" + identity["platform_id"])
        if len(self.sessions) >= 128:
            raise ValueError("编辑会话较多，请稍后再试")
        member = None

        async def closed():
            if member:
                self.portal.sessions.revoke(member.key)
            if hasattr(session, "id"):
                self.sessions.pop(session.id, None)

        async def dispatch(request):
            if not member or not self.portal.sessions.live(member):
                return {"status": 401, "data": {"detail": "会话已失效，请重新获取链接"}}
            path, method = request.get("path"), request.get("method")
            if (not isinstance(path, str) or len(path) > 2048 or not self.api_path.fullmatch(path.split("?", 1)[0])
                    or "%" in path.split("?", 1)[0] or any(c in path for c in "#\\\r\n") or method not in {"GET", "POST"}):
                raise ValueError("Invalid editor API")
            response = await self.http.request(method, self.base + "/api/" + path,
                headers={"Authorization": f"Bearer {member.key}"},
                json=request.get("body") if method == "POST" else None)
            return {"status": response.status_code, "data": response.json()}

        session = EditorSession(self.url, self.token, handler=dispatch, on_close=closed)
        try:
            entry = self.page_path if page_path is None else page_path
            url = await session.start(**({"page_path": entry} if entry is not None else {}))
            member = self.portal.sessions.issue(**identity, ttl=max(1, session.deadline - monotonic()))
            self.sessions[session.id] = session
            return url
        except BaseException:
            await session.close()
            raise

    async def close(self):
        await asyncio.gather(*(session.close() for session in list(self.sessions.values())))
        await self.http.aclose()
