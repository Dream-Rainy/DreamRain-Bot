"""Private ASGI dispatch for the trusted editor; never mounted on the bot server."""
from __future__ import annotations

from arcade_helper.web import BASE
from dataclasses import asdict
from typing import Annotated

from arcade_helper.aliases import AliasService
from arcade_helper.aliases.models import AliasConflictError, AliasPermissionError
from arcade_helper.catalog.importer import prepare_arcade_catalog
from arcade_helper.core.errors import ArcadeHelperError
from arcade_helper.storage.tortoise.catalog_models import CatalogImport, GameSong, SongReference
from arcade_helper.storage.tortoise.alias_models import AliasRequest
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from tortoise.exceptions import DoesNotExist

from .session import EditorSessions

Positive = Annotated[StrictInt, Field(gt=0)]
Cursor = Annotated[int, Query(ge=0)]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Submission(Body):
    operation: str = "ADD_ALIAS"
    payload: dict
    idempotency_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(default="", max_length=2000)


class Version(Body):
    version: Positive


class Decision(Version):
    approve: StrictBool
    reason: str = Field(min_length=1, max_length=2000)
    confirmed_target_versions: dict[str, StrictInt] | None = None


class AliasPortal:
    def __init__(self, client, sessions: EditorSessions):
        self.client, self.sessions = client, sessions
        self.relay = None
        self.router = self.make_router()

    async def close(self):
        if self.relay:
            await self.relay.close()
        self.sessions.clear()

    def member(self, request):
        return request.state.alias_member

    def admin(self, request):
        member = self.member(request)
        if not self.sessions.admin(member):
            raise HTTPException(403, "此操作需要管理员权限")
        return member

    def service(self, request, *, mine=False):
        member = self.member(request)
        old = self.client.data.aliases
        return AliasService(self.client.identities, policy=self.sessions.policy(member, mine),
                            daily_limit=old.daily_limit, pending_limit=old.pending_limit)

    def profile(self, member):
        return {"user_id": member.user_id, "label": member.label, "admin": self.sessions.admin(member),
                "expires_in": max(0, int(member.expires - self.sessions.clock()))}

    async def songs(self, ids):
        rows = await GameSong.filter(id__in=set(ids)).values(
            "id", "work_id", "game_code", "title", "artist", "active", "chart_variant", "version", "edition_key")
        native = await SongReference.filter(game_song_id__in=set(ids), provider="catalog", namespace="native").order_by("present", "id").values("game_song_id", "external_key")
        public = {r["game_song_id"]: r["external_key"] for r in native}
        for row in rows:
            row["public_id"] = public.get(row["id"], row["id"])
        return {row["id"]: row for row in rows}

    def make_router(self):
        portal = self

        class PortalRoute(APIRoute):
            def get_route_handler(self):
                original = super().get_route_handler()

                async def handle(request):
                    try:
                        write = request.method not in {"GET", "HEAD"}
                        scheme, _, key = request.headers.get("authorization", "").partition(" ")
                        request.state.alias_member = portal.sessions.member(key if scheme == "Bearer" else None)
                        if write:
                            chunks, size = [], 0
                            async for chunk in request.stream():
                                size += len(chunk)
                                if size > 65536:
                                    raise HTTPException(413, "内容太长，请缩短提交")
                                chunks.append(chunk)
                            request._body = b"".join(chunks)
                        response = await original(request)
                    except HTTPException as exc:
                        response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
                    except AliasPermissionError as exc:
                        response = JSONResponse({"detail": str(exc)}, status_code=403)
                    except AliasConflictError as exc:
                        response = JSONResponse({"detail": str(exc), "refresh": True}, status_code=409)
                    except DoesNotExist:
                        response = JSONResponse({"detail": "记录不存在或已被更新，请刷新"}, status_code=404)
                    except RequestValidationError:
                        response = JSONResponse({"detail": "提交格式不正确，请检查必填内容"}, status_code=422)
                    except (ValueError, KeyError, TypeError) as exc:
                        response = JSONResponse({"detail": str(exc)}, status_code=422)
                    except ArcadeHelperError as exc:
                        response = JSONResponse({"detail": str(exc)}, status_code=503)
                    except Exception:
                        logger.exception("Alias portal request failed")
                        response = JSONResponse({"detail": "服务暂时不可用，请稍后重试"}, status_code=500)
                    response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                        "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
                    return response
                return handle

        router = APIRouter(prefix=BASE, route_class=PortalRoute)

        @router.get("/api/me")
        async def me(request: Request):
            return self.profile(self.member(request))

        @router.post("/api/logout")
        async def logout(request: Request, body: Body):
            self.sessions.members.pop(self.member(request).key, None)
            return {"ok": True}

        @router.get("/api/games")
        async def games():
            return sorted(set(await GameSong.filter(active=True).values_list("game_code", flat=True)))

        @router.get("/api/search")
        async def search(q: str = Query(min_length=1, max_length=256), game: str | None = Query(default=None, max_length=32)):
            result = await self.client.catalog.search_all(q, game_code=game or None, allow_semantic=False)
            hits = list(result.candidates)[:50]
            metadata = await self.songs([c.game_song_id for c in hits])
            return {"items": [{**asdict(c), **metadata.get(c.game_song_id, {})} for c in hits],
                    "total": len(result.candidates), "unavailable_games": result.unavailable_games,
                    "inferred_game": result.inferred_game}

        @router.get("/api/songs/{song_id}")
        async def song(request: Request, song_id: int):
            row = await GameSong.get(id=song_id)
            related = await GameSong.filter(work_id=row.work_id).values_list("id", flat=True)
            metadata = await self.songs(related)
            return {"song": metadata[row.id], "music_variant": row.catalog_payload.get("music_variant"),
                    "entries": list(metadata.values()), "evidence": await self.service(request).get_effective_aliases(song_id, include_inactive=self.sessions.admin(self.member(request)), actor_id=self.member(request).user_id)}

        @router.post("/api/requests")
        async def submit(request: Request, body: Submission):
            if body.operation != "ADD_ALIAS":
                self.admin(request)
            payload = body.payload
            for key in ("game_song_id", "evidence_id", "target_id", "previous_request_id"):
                if key in payload and payload[key] is not None and (type(payload[key]) is not int or payload[key] <= 0):
                    raise ValueError(f"{key} 必须是正整数")
            if body.operation == "MAP_SOURCE_RECORD" and payload.get("decision") == "bind":
                target = await GameSong.get(id=payload["target_id"])
                if not target.active or target.game_code != payload.get("game_code"):
                    raise ValueError("只能绑定到同一游戏的有效收录")
            request_id = await self.service(request).submit(actor_id=self.member(request).user_id,
                operation=body.operation, payload=payload, reason=body.reason, idempotency_key=body.idempotency_key)
            return {"id": request_id}

        @router.get("/api/requests")
        async def requests(request: Request, status: str = Query(default="pending", max_length=24), after: Cursor = 0, mine: bool = True):
            if not mine:
                self.admin(request)
            result = await self.service(request, mine=mine).list_requests(actor_id=self.member(request).user_id,
                status=status or None, after_id=after, limit=30, include_details=False)
            owned = set(await AliasRequest.filter(id__in=[r["id"] for r in result["items"]],
                actor_id=self.member(request).user_id, status="pending").values_list("id", flat=True))
            for item in result["items"]:
                item["can_withdraw"] = item["id"] in owned
            return result

        @router.get("/api/requests/{request_id}")
        async def detail(request: Request, request_id: int):
            data = await self.service(request).get_request(request_id, actor_id=self.member(request).user_id)
            ids = [int(k.split(":")[1]) for k in data["current_target_versions"] if k.startswith("song:")]
            data["songs"] = list((await self.songs(ids)).values())
            data["stale"] = data["target_versions"] != data["current_target_versions"]
            data["can_withdraw"] = data["actor_id"] == self.member(request).user_id and data["status"] == "pending"
            return data

        @router.post("/api/requests/{request_id}/review")
        async def review(request: Request, request_id: int, body: Decision):
            member = self.admin(request)
            await self.service(request).review(request_id, actor_id=member.user_id, approve=body.approve,
                expected_version=body.version, reason=body.reason, expected_target_versions=body.confirmed_target_versions)
            self.client.data.catalog.invalidate_search_cache()
            return {"ok": True}

        @router.post("/api/requests/{request_id}/withdraw")
        async def withdraw(request: Request, request_id: int, body: Version):
            await self.service(request).withdraw(request_id, actor_id=self.member(request).user_id, expected_version=body.version)
            return {"ok": True}

        @router.get("/api/candidates")
        async def candidates(request: Request, after: Cursor = 0):
            member = self.admin(request)
            rows = await self.service(request).list_candidates(actor_id=member.user_id, after_id=after, limit=30)
            metadata = await self.songs([r[k] for r in rows for k in ("left_id", "right_id")])
            for row in rows:
                row["songs"] = [metadata.get(row["left_id"]), metadata.get(row["right_id"])]
                row["stale"] = {str(s["id"]): s["version"] for s in row["songs"] if s} != row["target_versions"]
            return {"items": rows, "next_cursor": rows[-1]["id"] if rows else after, "has_more": len(rows) == 30}

        @router.post("/api/candidates/{candidate_id}/decide")
        async def decide(request: Request, candidate_id: int, body: Decision):
            member = self.admin(request)
            await self.service(request).decide_candidate(candidate_id, actor_id=member.user_id,
                accept=body.approve, expected_version=body.version, reason=body.reason)
            self.client.data.catalog.invalidate_search_cache()
            return {"ok": True}

        @router.post("/api/associate")
        async def associate(request: Request, body: Body):
            member = self.admin(request)
            result = await self.service(request).associate(actor_id=member.user_id)
            self.client.data.catalog.invalidate_search_cache()
            return result

        @router.get("/api/imports")
        async def imports(request: Request):
            self.admin(request)
            rows = await CatalogImport.filter(provider="arcade_songs").values("id", "provider", "namespace", "game_code", "sync_version", "report", "updated_at")
            for row in rows:
                report = row.pop("report") or {}
                row["pending"] = len(report.get("pending", []))
                row["available"] = report.get("available_song_count", 0)
                row["outcome"] = report.get("outcome", "complete")
            return rows

        @router.get("/api/imports/{import_id}")
        async def pending(request: Request, import_id: int, after: Cursor = 0):
            self.admin(request)
            row = await CatalogImport.get(id=import_id, provider="arcade_songs")
            items = (row.report or {}).get("pending", [])
            return {"id": row.id, "game_code": row.game_code, "provider": row.provider, "namespace": row.namespace,
                    "sync_version": row.sync_version, "items": items[after:after+30], "next_cursor": after+30,
                    "has_more": after+30 < len(items)}

        @router.get("/api/imports/{import_id}/records")
        async def records(request: Request, import_id: int, key: str = Query(max_length=512)):
            self.admin(request)
            row = await CatalogImport.get(id=import_id, provider="arcade_songs")
            records, _ = prepare_arcade_catalog(row.observed_payload or row.raw_payload or {})
            return [{"external_key": r.external_key, "record_selector": r.selector, "source_record_key": r.source_record_key,
                     "title": r.song.title, "artist": r.song.artist, "edition_key": getattr(r.song, "edition_key", ""),
                     "chart_variant": r.song.chart_variant, "music_variant": getattr(r.song, "music_variant", None), "raw": r.raw}
                    for r in records if r.external_key == key]

        @router.get("/api/events")
        async def events(request: Request, after: Cursor = 0):
            return await self.service(request).events(actor_id=self.member(request).user_id, after_id=after, limit=30)

        return router
