"""Bot-wired song catalog facade for LXNS-backed game data."""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import replace
from time import monotonic
from typing import Any

from arcade_helper import ArcadeHelperClient
from arcade_helper.aliases.models import alias_key, AliasCandidate, AliasResolution
from arcade_helper.core.song import SongData
from arcade_helper.core.song_identity import parse_chart_title
from arcade_helper.search import MatchType, SongQueryResult, SongSearchService, is_short_song_query
from arcade_helper.storage.tortoise import TortoiseSongStore
from arcade_helper.storage.tortoise.catalog_models import SongReference, GameSong

from ...shared.game.adapter import DomainAdapter
from ...shared.search.embedding_cache import (
    rebuild_song_embeddings,
    rebuild_song_embeddings_from_songs,
    search_song_by_embedding,
    embedding_enabled, embedding_model, embedding_endpoint, _stop_query_tasks,
)
from ...shared.search.reranker import rerank_song_results, reranker_enabled, reranker_threshold, song_work_key
from .plugin_data import plugin_data


_DB_GAME_CODES = {"maimai", "chunithm"}
_UNCERTAIN_BM25_EMBEDDING_MIN_MARGIN = 4.0


def _is_uncertain_bm25(results: list[SongQueryResult], game_code=None) -> bool:
    works = {}
    for result in sorted(results, key=lambda r: r.match_score, reverse=True):
        works.setdefault(song_work_key(result, game_code), result)
    ranked = list(works.values())
    if len(ranked) < 2 or ranked[0].match_type is not MatchType.BM25:
        return False
    return (ranked[0].match_score - ranked[1].match_score) < 8.0


class BotCatalogClient:
    """Single entrypoint for loading, syncing, and scheduling song catalogs."""

    def __init__(
        self,
        data: ArcadeHelperClient,
        *,
        song_store: TortoiseSongStore,
        logger: Any,
        auto_sync_enabled: bool = True,
        auto_sync_interval_seconds: int = 86400,
        auto_sync_startup_delay_seconds: int = 300,
        background_refresh_delay_seconds: float = 5.0,
    ) -> None:
        self.data = data
        self.songs = song_store
        self.service = data.catalog
        self.search = SongSearchService(self)
        self.logger = logger
        self.auto_sync_enabled = auto_sync_enabled
        self.auto_sync_interval_seconds = max(60, int(auto_sync_interval_seconds))
        self.auto_sync_startup_delay_seconds = max(0, int(auto_sync_startup_delay_seconds))
        self.background_refresh_delay_seconds = max(0.0, float(background_refresh_delay_seconds))
        self._refresh_task: asyncio.Task[str] | None = None
        self._last_refresh_result: str | None = None
        self._auto_sync_task: asyncio.Task[None] | None = None
        self._cache_task: asyncio.Task[None] | None = None
        self._identity_revision = None
        self._embedding_generations = {}
        self._embedding_inputs = {}
        self._input_locks = {}

    def _domain_adapters(self) -> list[DomainAdapter]:
        from ...domains.chunithm.chunithm_adapter import get_chunithm_adapter
        from ...domains.maimai.maimai_adapter import get_maimai_adapter

        return [get_maimai_adapter(), get_chunithm_adapter()]

    @staticmethod
    def _song_index_attr(adapter: DomainAdapter) -> str:
        return str(getattr(adapter, "song_index_attr"))

    @staticmethod
    def _song_store_attr(adapter: DomainAdapter) -> str:
        return str(getattr(adapter, "song_store_attr"))

    async def fetch_maimai_raw_data(self) -> dict[int, Any]:
        result = await self.service.fetch_game_raw_data(
            "maimai",
            current_data_version=plugin_data.data_version,
        )
        plugin_data.data_version = result.data_version
        return result.songs

    async def fetch_chunithm_raw_data(self) -> dict[int, Any]:
        result = await self.service.fetch_game_raw_data("chunithm")
        return result.songs

    async def fetch_maimai_song_collections(self, song_id: int) -> list[dict[str, Any]]:
        self.logger.debug(f"获取乐曲 {song_id} 的收藏信息")
        return await self.service.fetch_maimai_song_collections(song_id)

    async def get_song_by_id(self, game_code: str, song_id: int):
        if self._uses_db_catalog(game_code) or self.aliases_enabled:
            return await self.service.get_song_by_id(game_code, song_id)
        songs = await self.data.catalog.arcade_songs.catalog(game_code)
        return songs.get(song_id)

    async def get_songs_by_ids(self, game_code: str, song_ids: list[int]):
        if not song_ids:
            return {}
        if self._uses_db_catalog(game_code) or self.aliases_enabled:
            batch = getattr(self.service, "get_songs_by_ids", None)
            if batch is not None:
                return await batch(game_code, song_ids)
            songs = {}
            for sid in dict.fromkeys(song_ids):
                song = await self.service.get_song_by_id(game_code, sid)
                if song is not None:
                    songs[sid] = song
            return songs
        songs = await self.data.catalog.arcade_songs.catalog(game_code)
        return {sid: songs[sid] for sid in dict.fromkeys(song_ids) if sid in songs}

    async def search_song(
        self,
        game_code: str,
        query: str | int,
    ) -> list[SongQueryResult]:
        if self.aliases_enabled:
            resolution = await self.search_all(str(query), game_code=game_code, allow_semantic=not isinstance(query, int))
            candidates = resolution.candidates
            if not candidates:
                return []
            ids = await self.public_song_ids([(game_code, c.game_song_id) for c in candidates])
            songs = await self.get_songs_by_ids(game_code, [ids[(game_code, c.game_song_id)] for c in candidates])
            return [SongQueryResult(ids[(game_code, c.game_song_id)], c.title, MatchType(c.match_type), c.score,
                                    c.matched_text, songs[ids[(game_code, c.game_song_id)]])
                    for c in candidates if ids[(game_code, c.game_song_id)] in songs]
        results = await self.search.search_candidates(query, game_code=game_code)
        results = await self._validate_results(query, results, [game_code])
        songs = await self.get_songs_by_ids(game_code, [r.song_id for r in results])
        return [replace(r, song_data=songs[r.song_id], title=songs[r.song_id].title) for r in results if r.song_id in songs]

    async def _validate_results(self, query: str | int, results: list[SongQueryResult], games: list[str],
                                *, rerank_cache: dict | None = None) -> list[SongQueryResult]:
        """One acceptance policy for scoped and cross-game text candidates."""
        game_code = games[0] if len(games) == 1 else None
        if isinstance(query, int) or is_short_song_query(query):
            return results
        if results and not _is_uncertain_bm25(results, game_code):
            return results
        options = {"score_cache": rerank_cache} if rerank_cache is not None else {}
        reranker_attempted = bool(results and reranker_enabled())
        if results:
            try:
                reranked_results = await rerank_song_results(self, game_code, str(query), results, **options)
            except Exception as e:
                self.logger.warning(f"[{game_code}] reranker 搜索失败，已跳过: {e}")
            else:
                if reranked_results is not None:
                    return reranked_results
        if not embedding_enabled():
            return results
        semantic_acceptance = not reranker_attempted and reranker_enabled() and reranker_threshold() > 0
        if not results and not semantic_acceptance:
            return []
        semaphore = asyncio.Semaphore(2)
        async def find(game):
            async with semaphore:
                try:
                    rows = await search_song_by_embedding(self, game, str(query), hydrate=False, internal_ids=self.aliases_enabled)
                    markers = parse_chart_title(str(query))[1]
                    if rows is not None and markers:
                        rows = [r for r in rows if tuple(r.song_data.chart_variant or ()) == markers]
                    return game, rows
                except Exception as e:
                    self.logger.warning(f"[{game}] embedding 搜索失败，已跳过: {e}")
                    return game, None
        by_game = dict(await asyncio.gather(*(find(game) for game in games)))
        unverified = [r for r in results if by_game.get(getattr(r.song_data, "game_code", None) or game_code) is None]
        embedding_results = sorted([r for rows in by_game.values() if rows is not None for r in rows],
                                   key=lambda r: r.match_score, reverse=True)
        if not embedding_results:
            return unverified
        if results:
            works = {}
            for row in embedding_results:
                works.setdefault(song_work_key(row, game_code), row)
            ranked = list(works.values())
            if len(ranked) > 1 and ranked[0].match_score - ranked[1].match_score < _UNCERTAIN_BM25_EMBEDDING_MIN_MARGIN:
                return unverified
            best = song_work_key(ranked[0], game_code)
            embedding_results = [r for r in embedding_results if song_work_key(r, game_code) == best]
        text_works = {song_work_key(result, game_code) for result in results}
        supported = [result for result in embedding_results if song_work_key(result, game_code) in text_works]
        if supported:
            seen = {(getattr(r.song_data, "game_code", None) or game_code, r.song_id) for r in supported}
            return supported + [r for r in unverified if (getattr(r.song_data, "game_code", None) or game_code, r.song_id) not in seen]
        if not semantic_acceptance:
            return unverified
        try:
            accepted = await rerank_song_results(self, game_code, str(query), embedding_results, **options)
            return unverified if accepted is None else accepted
        except Exception as e:
            self.logger.warning(f"[{game_code}] 语义候选验证失败: {e}")
            return unverified

    async def rebuild_search_embeddings(self, game_code: str) -> dict[str, Any]:
        gc = str(game_code).strip().lower()
        if gc in {"maimai", "chunithm"} or self.aliases_enabled:
            return await rebuild_song_embeddings(self, gc)

        songs = await self.data.catalog.arcade_songs.catalog(gc)
        alias_records = [
            (song_id, alias)
            for song_id, song in songs.items()
            for alias in (getattr(song, "aliases", None) or [])
        ]
        return await rebuild_song_embeddings_from_songs(gc, songs, alias_records=alias_records)

    async def get_song_aliases(self, game_code: str, song_query: str | int) -> dict | None:
        return await self.search.get_song_aliases(song_query, game_code=game_code)

    async def load_all_songs(self, game_code: str):
        if self._uses_db_catalog(game_code) or self.aliases_enabled:
            return await self.service.load_all_songs(game_code)
        return await self.data.catalog.arcade_songs.catalog(game_code)

    async def load_song_index(self, game_code: str) -> dict[int, str]:
        if self._uses_db_catalog(game_code) or self.aliases_enabled:
            return await self.service.load_song_index(game_code)
        songs = await self.data.catalog.arcade_songs.catalog(game_code)
        return {song_id: song.title for song_id, song in songs.items()}

    async def query_title_exact(self, game_code: str, title: str):
        if self._uses_db_catalog(game_code) or self.aliases_enabled:
            query = getattr(self.service, "query_title_exact", None)
            if query is not None:
                return await query(game_code, title)
        return [(sid, text) for sid, text in (await self.load_song_index(game_code)).items() if text.lower() == title.lower()]

    async def load_search_songs(self, game_code: str):
        return (await self.load_embedding_inputs(game_code))[0]

    async def _load_search_songs(self, game_code: str):
        if self._uses_db_catalog(game_code) or self.aliases_enabled:
            load = getattr(self.service, "load_search_songs", self.service.load_all_songs)
            return await load(game_code)
        return await self.data.catalog.arcade_songs.catalog(game_code)

    async def load_embedding_inputs(self, game_code: str):
        async with self._input_locks.setdefault(game_code, asyncio.Lock()):
            revision = await self.get_revision()
            identities = getattr(self.service, "identities", None)
            db = getattr(identities, "_db", None)
            generation = (db, revision)
            cached = self._embedding_inputs.get(game_code)
            if (cached is not None and cached[0] == generation
                    and (revision is not None or monotonic() - cached[3] < 270)):
                return cached[1], cached[2]
            songs = await self._load_search_songs(game_code)
            populated = bool(songs) and all("aliases" in song.model_fields_set for song in songs.values())
            aliases = ([(sid, text) for sid, song in songs.items() for text in song.aliases]
                       if populated else await self.load_alias_records(game_code))
            if not populated:
                by_song = {}
                for sid, text in aliases:
                    by_song.setdefault(sid, []).append(text)
                songs = {sid: song.model_copy(update={"aliases": list(dict.fromkeys([
                    *song.aliases, *by_song.get(sid, []),
                ]))}) for sid, song in songs.items()}
            if (await self.get_revision() != revision
                    or getattr(getattr(self.service, "identities", None), "_db", None) is not db):
                raise ValueError("曲库已变化，请重新构建搜索缓存")
            self._embedding_inputs[game_code] = (generation, songs, aliases, monotonic())
            return songs, aliases

    async def query_alias_exact(self, game_code: str, alias_lower: str) -> list[tuple[int, str]]:
        if self.aliases_enabled:
            return self._dedupe_alias_records(await self.service.query_alias_exact(game_code, alias_lower))
        if self._uses_db_catalog(game_code):
            records = await self.service.query_alias_exact(game_code, alias_lower)
        else:
            songs = await self.data.catalog.arcade_songs.catalog(game_code)
            records = [
                (song_id, alias)
                for song_id, song in songs.items()
                for alias in (getattr(song, "aliases", None) or [])
                if alias.lower() == alias_lower
            ]
        return self._dedupe_alias_records(records)

    async def load_alias_records(self, game_code: str) -> list[tuple[int, str]]:
        if self._uses_db_catalog(game_code) or self.aliases_enabled:
            records = await self.service.load_alias_records(game_code)
        else:
            songs = await self.data.catalog.arcade_songs.catalog(game_code)
            records = [
                (song_id, alias)
                for song_id, song in songs.items()
                for alias in (getattr(song, "aliases", None) or [])
            ]
        return self._dedupe_alias_records(records)

    async def get_song_aliases_for_song_id(self, game_code: str, song_id: int) -> list[str]:
        if self._uses_db_catalog(game_code) or self.aliases_enabled:
            aliases = await self.service.get_song_aliases_for_song_id(game_code, song_id)
        else:
            song = await self.get_song_by_id(game_code, song_id)
            aliases = list(getattr(song, "aliases", None) or []) if song is not None else []
        return self._dedupe_aliases(aliases)

    @property
    def aliases_enabled(self) -> bool:
        store = getattr(self.service, "identities", None)
        return bool(store is not None and store.enable_aliases)

    async def get_revision(self) -> int | None:
        method = getattr(self.service, "get_revision", None)
        return await method() if method else None

    async def search_all(self, query: str, *, game_code: str | None = None, allow_semantic: bool = True):
        """Unified persistent query core; alias targets request text-only resolution."""
        if query == "":
            return AliasResolution("unknown", game_code, "candidates_require_choice", ())
        validate = allow_semantic and not is_short_song_query(query) and (reranker_enabled() or embedding_enabled())
        rerank_cache = {}
        for _ in range(3):
            before = await self.get_revision() if validate else None
            result = await self.service.search_all(query, game_code=game_code, text_only=True)
            candidates = tuple(c for c in result.candidates if c.match_type != "embedding")
            exact = tuple(c for c in candidates if c.match_type.startswith("exact_"))
            if exact:
                candidates = exact
            elif any(c.match_type != "bm25" for c in candidates):
                candidates = tuple(c for c in candidates if c.match_type != "bm25")
            if not validate or exact:
                return replace(result, candidates=candidates)
            rows = [SongQueryResult(c.game_song_id, c.title, MatchType(c.match_type), c.score, c.matched_text,
                    SongData(id=c.game_song_id, title=c.title, work_id=c.work_id, game_code=c.game_code)) for c in candidates]
            if rows and not _is_uncertain_bm25(rows, game_code):
                return replace(result, candidates=candidates)
            if not rows and not (embedding_enabled() and reranker_enabled() and reranker_threshold() > 0):
                return replace(result, candidates=())
            games = ([game_code] if game_code else
                     sorted(await GameSong.filter(active=True).distinct().values_list("game_code", flat=True)))
            if _is_uncertain_bm25(rows, game_code) and reranker_enabled():
                # Only ambiguous text needs richer documents; these remain payload-free.
                for game in {c.game_code for c in candidates}:
                    metadata = await self.service.identities.get_search_songs_by_ids(game,
                                   [c.game_song_id for c in candidates if c.game_code == game])
                    rows = [replace(r, song_data=metadata[r.song_id]) if r.song_data.game_code == game and r.song_id in metadata else r for r in rows]
            accepted = await self._validate_results(query, rows, games, rerank_cache=rerank_cache)
            originals = {(c.game_code, c.game_song_id): c for c in candidates}
            selected = []
            for row in accepted:
                song = row.song_data
                key = (song.game_code, row.song_id)
                original = originals.get(key)
                selected.append(replace(original, match_type=row.match_type.value, score=row.match_score) if original else
                    AliasCandidate(row.song_id, str(song.work_id), song.game_code, row.title, row.matched_text,
                                   row.match_type.value, row.match_score, chart_variant=song.chart_variant))
            if await self.get_revision() == before:
                return AliasResolution("explicit" if game_code else "ambiguous" if selected else "unknown", game_code,
                                       "explicit_game" if game_code else "candidates_require_choice", tuple(selected))
        raise ValueError("曲库在查询期间连续变化，请重试")

    async def internal_song_id(self, game_code: str, song_id: int) -> int:
        game_code = str(game_code).strip().lower()
        if song_id <= 0:
            raise ValueError("歌曲 ID 必须为正整数")
        if game_code in _DB_GAME_CODES:
            internal_id = await self.service.identities.resolve_reference(
                game_code, str(song_id), provider="catalog", namespace="native",
            )
        else:
            song = await self.service.get_song_by_id(game_code, song_id)
            internal_id = song.game_song_id if song else None
        if internal_id is None:
            raise ValueError("歌曲尚未导入或 ID 无效，请先同步曲库")
        return internal_id

    async def public_song_id(self, game_code: str, internal_id: int) -> int:
        return (await self.public_song_ids([(game_code, internal_id)]))[(game_code, internal_id)]

    async def public_song_ids(self, songs: list[tuple[str, int]]) -> dict[tuple[str, int], int]:
        result = {pair: pair[1] for pair in songs if pair[0] not in _DB_GAME_CODES}
        native = {pair for pair in songs if pair[0] in _DB_GAME_CODES}
        if not native:
            return result
        references = await SongReference.filter(
            game_song_id__in={pair[1] for pair in native}, game_code__in={pair[0] for pair in native},
            provider="catalog", namespace="native", present=True,
        ).order_by("id").values("game_song_id", "game_code", "external_key")
        for reference in references:
            pair = reference["game_code"], reference["game_song_id"]
            if pair in native and reference["external_key"].isdecimal():
                result.setdefault(pair, int(reference["external_key"]))
        if native - result.keys():
            raise ValueError("内部收录没有可用的游戏原生 ID")
        return result

    async def alias_candidate_result(self, candidate) -> SongQueryResult:
        song_id = await self.public_song_id(candidate.game_code, candidate.game_song_id)
        return SongQueryResult(
            song_id=song_id, title=candidate.title,
            match_type=MatchType(candidate.match_type), match_score=candidate.score,
            matched_text=candidate.matched_text,
            song_data=await self.get_song_by_id(candidate.game_code, song_id),
        )

    async def get_song_with_difficulty(
        self,
        game_code: str,
        song_id: int,
        song_type: str = "standard",
        level_index: int = 3,
    ) -> dict | None:
        return await self.service.get_song_with_difficulty(
            game_code,
            song_id,
            song_type=song_type,
            level_index=level_index,
        )

    async def sync_songs(self, game_code: str, song_data: dict[int, Any]) -> None:
        await self.service.sync_songs(game_code, song_data)
        self.invalidate_alias_cache(game_code)

    async def sync_maimai_collections(self, song_id: int, collections: list[dict[str, Any]]) -> None:
        await self.service.sync_maimai_collections(song_id, collections)

    def invalidate_alias_cache(self, game_code: str) -> None:
        try:
            self.search.invalidate_alias_cache(game_code)
            self.service.invalidate_search_cache(game_code)
        except Exception as e:
            self.logger.warning(f"[{game_code}] 失效别名缓存失败（可忽略，下次 TTL 到期会自动刷新）: {e}")

    @staticmethod
    def _dedupe_alias_records(records: list[tuple[int, str]]) -> list[tuple[int, str]]:
        result: list[tuple[int, str]] = []
        seen: set[tuple[int, str]] = set()
        for song_id, alias in records:
            key = (int(song_id), str(alias).lower())
            if key in seen:
                continue
            seen.add(key)
            result.append((int(song_id), str(alias)))
        return result

    @staticmethod
    def _dedupe_aliases(aliases: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for alias in aliases:
            text = str(alias)
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    @staticmethod
    def _uses_db_catalog(game_code: str) -> bool:
        return str(game_code).strip().lower() in _DB_GAME_CODES

    async def _sync_adapter_from_remote(self, adapter: DomainAdapter) -> bool:
        gc = adapter.game_code
        try:
            self.logger.info("=" * 50)
            self.logger.info(f"开始后台更新 {gc} 乐曲数据")
            self.logger.info("=" * 50)

            result = await self.service.sync_game_from_remote(
                gc,
                current_data_version=plugin_data.data_version if gc == "maimai" else None,
                include_songs=False,
            )
            if result.status == "already_running":
                self.logger.info(f"{gc} 乐曲数据后台更新跳过：同步已在进行中")
                return False
            if not result.ok:
                raise result.error or RuntimeError("catalog sync failed")
            if gc == "maimai":
                plugin_data.data_version = result.data_version
            setattr(
                plugin_data,
                self._song_index_attr(adapter),
                await self.service.load_song_index(gc),
            )
            setattr(plugin_data, self._song_store_attr(adapter), {})
            adapter.clear_image_cache()
            self.invalidate_alias_cache(gc)
            self._embedding_generations.pop(gc, None)
            self.logger.info(f"{gc} 乐曲数据后台更新完成")
            return True
        except Exception as e:
            traceback.print_exc()
            self.logger.error(f"后台更新 {gc} 乐曲数据失败，继续使用本地数据: {e}")
            return False

    async def sync_song_data_from_remote(self) -> str:
        adapters = self._domain_adapters()
        results = await asyncio.gather(*(self._sync_adapter_from_remote(adapter) for adapter in adapters))

        succeeded = [adapter.display_name for adapter, ok in zip(adapters, results, strict=True) if ok]
        failed = [adapter.display_name for adapter, ok in zip(adapters, results, strict=True) if not ok]
        if self.aliases_enabled:
            try:
                reports = await self.service.prepare_catalogs(force_refresh=True)
                succeeded.extend(reports)
                results.extend(True for _ in reports)
            except Exception as exc:
                self.logger.warning(f"通用街机曲库同步部分失败，继续使用已发布数据: {exc}")
                failed.append("arcade-songs")
                results.append(False)
        ok_count = sum(1 for ok in results if ok)
        if ok_count == len(results):
            self.logger.info("全部乐曲数据后台同步完成")
            return f"后台同步完成：{'、'.join(succeeded)} 全部成功"
        elif ok_count:
            self.logger.warning("乐曲数据后台同步部分完成，失败的游戏继续使用本地数据")
            return f"后台同步完成：成功 {'、'.join(succeeded)}；失败 {'、'.join(failed)}"
        else:
            self.logger.warning("乐曲数据后台同步全部失败，继续使用本地数据")
            return f"后台同步完成：全部失败（{'、'.join(failed)}）"

    async def _run_background_refresh(self) -> str:
        await asyncio.sleep(self.background_refresh_delay_seconds)
        return await self.sync_song_data_from_remote()

    def _on_refresh_task_done(self, task: asyncio.Task[str]) -> None:
        current = self._refresh_task is task
        try:
            result = task.result()
            if current:
                self._last_refresh_result = result
        except asyncio.CancelledError:
            self.logger.warning("乐曲数据后台同步任务已取消")
        except Exception as e:
            if current:
                self._last_refresh_result = f"后台同步异常：{e}"
            self.logger.error(f"乐曲数据后台同步任务异常结束: {e}")
        finally:
            if current:
                self._refresh_task = None

    def start_background_refresh(self) -> bool:
        if self._refresh_task and not self._refresh_task.done():
            return False

        self._last_refresh_result = None
        self._refresh_task = asyncio.create_task(self._run_background_refresh())
        self._refresh_task.add_done_callback(self._on_refresh_task_done)
        return True

    async def wait_for_refresh(self) -> str | None:
        if self._refresh_task is not None:
            return await self._refresh_task
        return self._last_refresh_result

    async def load_song_data_from_db(self) -> tuple[bool, str]:
        adapters = self._domain_adapters()
        indexes = await asyncio.gather(*(self.load_song_index(adapter.game_code) for adapter in adapters))

        loaded_games: list[str] = []
        for adapter, index in zip(adapters, indexes, strict=True):
            setattr(plugin_data, self._song_store_attr(adapter), {})
            if index:
                setattr(plugin_data, self._song_index_attr(adapter), index)
                loaded_games.append(f"{adapter.display_name} {len(index)} 首")

        if loaded_games:
            return True, "已加载本地数据库曲库索引：" + "，".join(loaded_games)
        return False, "本地数据库暂无可用曲库索引"

    async def refresh_song_data(self, *, manual: bool = False) -> tuple[bool, str]:
        local_available, local_msg = await self.load_song_data_from_db()
        if self._cache_task is None or self._cache_task.done():
            self._cache_task = asyncio.create_task(self._cache_refresh_loop())
        started = self.start_background_refresh()
        if manual:
            self.start_auto_sync()

        if started:
            return local_available, f"{local_msg}；已启动后台同步"
        return local_available, f"{local_msg}；后台同步已在进行中"

    async def _refresh_search_caches(self) -> None:
        revision = await self.get_revision()
        if self.aliases_enabled and self._identity_revision != revision:
            first = await GameSong.filter(active=True).only('title').first()
            if first is not None:
                await self.data.aliases.search_all(first.title)
            self._identity_revision = revision
        games = (await GameSong.filter(active=True).distinct().values_list('game_code', flat=True)
                 if self.aliases_enabled else [a.game_code for a in self._domain_adapters()])
        identities = getattr(self.service, "identities", None)
        generation = (getattr(identities, "_db", None), revision, embedding_endpoint(), embedding_model())
        for game in sorted(games):
            try:
                search = identities.text_search if self.aliases_enabled else self.search
                await search._warm_search_index(game)
            except Exception as exc:
                self.logger.warning(f'[{game}] 后台文本索引更新失败，稍后重试: {exc}')
            if not embedding_enabled():
                continue
            if self._embedding_generations.get(game) == generation:
                continue
            try:
                result = await self.rebuild_search_embeddings(game)
                if await self.get_revision() == revision:
                    self._embedding_generations[game] = generation
                self.logger.info(f"[{game}] 后台 embedding 缓存更新完成：{result['songs']} 首")
            except Exception as exc:
                self.logger.warning(f'[{game}] 后台 embedding 更新失败，稍后重试: {exc}')

    async def _cache_refresh_loop(self) -> None:
        while True:
            try:
                await self._refresh_search_caches()
            except Exception as exc:
                self.logger.warning(f'查歌缓存后台更新失败，稍后重试: {exc}')
            await asyncio.sleep(30)

    async def _auto_sync_loop(self) -> None:
        try:
            if self.auto_sync_startup_delay_seconds:
                await asyncio.sleep(self.auto_sync_startup_delay_seconds)
            while True:
                started = self.start_background_refresh()
                if started:
                    self.logger.info("自动曲库同步已触发后台任务")
                else:
                    self.logger.info("自动曲库同步跳过：后台同步已在进行中")
                await asyncio.sleep(self.auto_sync_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.error(f"自动曲库同步任务异常结束: {e}")

    def start_auto_sync(self) -> bool:
        if not self.auto_sync_enabled:
            return False
        if self._auto_sync_task and not self._auto_sync_task.done():
            return False

        self._auto_sync_task = asyncio.create_task(self._auto_sync_loop())
        return True

    async def stop_auto_sync(self) -> None:
        tasks = [t for t in (self._auto_sync_task, self._cache_task, self._refresh_task) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._auto_sync_task = self._cache_task = self._refresh_task = None
        await self.search._stop_index_builds()
        if self.aliases_enabled:
            await self.service.identities.text_search._stop_index_builds()
        await _stop_query_tasks()


__all__ = ["BotCatalogClient"]
