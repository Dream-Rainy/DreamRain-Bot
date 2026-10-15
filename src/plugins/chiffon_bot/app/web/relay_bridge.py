"""Bind outbound editor RPC to the identity proved by a private bot event."""
import asyncio
import re
from time import monotonic

import httpx
from fastapi import FastAPI
from arcade_helper.web.client import EditorSession

from arcade_helper.web import BASE

API_PATH = re.compile(r"(?:me|games|search|songs/[1-9][0-9]*|requests(?:/[1-9][0-9]*(?:/(?:review|withdraw))?)?|candidates(?:/[1-9][0-9]*/decide)?|associate|imports(?:/[1-9][0-9]*(?:/records)?)?|events|logout)")


class EditorBridge:
    def __init__(self, portal, url, token):
        self.portal, self.url, self.token = portal, url, token
        self.sessions = {}
        app = FastAPI()
        app.include_router(portal.router)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://alias-editor.internal")

    async def open(self, *, user_id, platform_id, adapter, label):
        self.portal.sessions.limit("editor:" + adapter + ":" + platform_id)
        if len(self.sessions) >= 128:
            raise ValueError("编辑会话较多，请稍后再试")
        member = None

        async def closed():
            if member:
                self.portal.sessions.members.pop(member.key, None)
            if hasattr(session, "id"):
                self.sessions.pop(session.id, None)

        async def dispatch(request):
            if not member or not self.portal.sessions.live(member):
                return {"status": 401, "data": {"detail": "编辑身份已失效，请重新创建会话"}}
            path, method = request.get("path"), request.get("method")
            if (not isinstance(path, str) or len(path) > 2048 or not API_PATH.fullmatch(path.split("?", 1)[0])
                    or "#" in path or method not in {"GET", "POST"}):
                raise ValueError("Invalid editor API")
            headers = {"Authorization": f"Bearer {member.key}"}
            response = await self.http.request(method, BASE + "/api/" + path, headers=headers,
                json=request.get("body") if method == "POST" else None)
            return {"status": response.status_code, "data": response.json()}

        session = EditorSession(self.url, self.token, handler=dispatch, on_close=closed)
        try:
            url = await session.start()
            member = self.portal.sessions.issue(user_id=user_id, platform_id=platform_id, adapter=adapter,
                label=label, ttl=max(1, session.deadline - monotonic()))
            self.sessions[session.id] = session
            return url
        except BaseException:
            await session.close()
            raise

    async def close(self):
        await asyncio.gather(*(session.close() for session in list(self.sessions.values())))
        await self.http.aclose()
