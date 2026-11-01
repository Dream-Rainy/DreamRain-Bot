"""Private module RPC. This router is never mounted on the bot's HTTP server."""
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from nonebot import logger

PATH = re.compile(r"(?:me|modules|logout|[a-z][a-z0-9_-]*/[A-Za-z0-9_/-]+)")
request_scope = ContextVar("management_request", default=None)


@dataclass
class Module:
    id: str
    title: str
    plugin: str
    dispatch: object
    authorize: object


def context_allowed(plugin, member, group_id=None):
    from src.plugins.permission_admin.core import get_permission_manager
    return get_permission_manager().is_context_allowed(plugin, int(member.platform_id), group_id)


class Portal:
    def __init__(self, sessions):
        self.sessions, self.modules = sessions, {}
        self.router = APIRouter(prefix="/manage/api")
        self.router.add_api_route("/{path:path}", self.handle, methods=["GET", "POST"])

    def register(self, module):
        if module.id in self.modules:
            raise ValueError(f"Duplicate management module: {module.id}")
        self.modules[module.id] = module

    async def handle(self, request: Request, path: str):
        started = perf_counter()
        scope = {"id": uuid4().hex, "active": True, "groups": {}, "auth_calls": 0, "auth_seconds": 0}
        token = request_scope.set(scope)
        try:
            if not PATH.fullmatch(path):
                raise HTTPException(404, "接口不存在")
            scheme, _, key = request.headers.get("authorization", "").partition(" ")
            member = self.sessions.member(key if scheme == "Bearer" else None)
            if not context_allowed("management", member):
                raise HTTPException(403, "后台访问已被禁用")
            body = None
            if request.method == "POST":
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 65536:
                        raise HTTPException(413, "提交内容过长")
                    chunks.append(chunk)
                try:
                    body = json.loads(b"".join(chunks))
                except (ValueError, UnicodeError):
                    raise HTTPException(422, "提交格式不正确")
                if not isinstance(body, dict):
                    raise HTTPException(422, "提交格式不正确")
            if path in {"me", "modules"}:
                if request.method != "GET":
                    raise HTTPException(405, "操作方式不正确")
                modules = []
                for module in self.modules.values():
                    if context_allowed(module.plugin, member) and await module.authorize(member):
                        modules.append({"id": module.id, "title": module.title})
                result = {"label": member.label, "admin": self.sessions.admin(member), "group_id": member.group_id,
                          "expires_in": max(0, int(member.expires - self.sessions.clock())), "modules": modules}
            elif path == "logout":
                if request.method != "POST" or body:
                    raise HTTPException(422, "退出格式不正确")
                self.sessions.revoke(member.key)
                result = {"ok": True}
            else:
                module_id, subpath = path.split("/", 1)
                module = self.modules.get(module_id)
                if not module:
                    raise HTTPException(404, "模块不存在")
                if not context_allowed(module.plugin, member) or not await module.authorize(member):
                    raise HTTPException(403, "没有该模块的访问权限")
                result = await module.dispatch(member, request.method, subpath, request.query_params, body)
            serializing = perf_counter()
            response = JSONResponse(result)
            scope["serialize_seconds"] = perf_counter() - serializing
            if len(response.body) > 480000:
                raise HTTPException(413, "结果过多，请缩小查询范围")
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
        except (ValueError, TypeError, KeyError):
            response = JSONResponse({"detail": "请求参数不正确"}, status_code=422)
        except Exception:
            logger.exception("Management request failed")
            response = JSONResponse({"detail": "服务暂时不可用，请稍后重试"}, status_code=503)
        finally:
            scope["active"] = False
            scope["groups"].clear()
            request_scope.reset(token)
            logger.debug("Management request id={} path={} seconds={:.4f} auth_calls={} auth_seconds={:.4f} serialize_seconds={:.4f}",
                         scope["id"], path if PATH.fullmatch(path) else "invalid", perf_counter()-started,
                         scope["auth_calls"], scope["auth_seconds"], scope.get("serialize_seconds", 0))
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        return response
