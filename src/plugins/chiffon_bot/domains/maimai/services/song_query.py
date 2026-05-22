from __future__ import annotations

from typing import Any, Literal

from ....integrations.lxns.plugin_data import plugin_data
from ....infra.db.models import ChuniSongAlias, MaiSongAlias
from ....shared.song_data import SongData
from ....shared.search.song_query import (
    MatchType as SharedMatchType,
    SongQueryResult as SharedSongQueryResult,
    get_song_aliases as shared_get_song_aliases,
    get_song_data as shared_get_song_data,
    get_song_data_from_id as shared_get_song_data_from_id,
    get_song_with_difficulty as shared_get_song_with_difficulty,
    invalidate_alias_cache as shared_invalidate_alias_cache,
    query_song_by_alias_exact as shared_query_song_by_alias_exact,
    query_song_by_id as shared_query_song_by_id,
    query_song_by_title_exact as shared_query_song_by_title_exact,
    query_song_fuzzy as shared_query_song_fuzzy,
    search_song as shared_search_song,
)
from .song_data_sync import (
    load_mai_song_by_id_from_db,
    load_mai_song_data_from_db,
    load_chuni_song_by_id_from_db,
    load_chuni_song_data_from_db,
)


GameCode = Literal["maimai", "chunithm"]


class MaimaiSongQueryAdapter:
    game_code = "maimai"

    def get_song_store(self) -> dict[int, SongData]:
        return plugin_data.mai_song_data

    def get_song_index(self) -> dict[int, str]:
        return plugin_data.mai_song_index

    def get_song_title(self, song_data: SongData) -> str:
        return str(getattr(song_data, "title", "") or "")

    async def get_song_by_id(self, song_id: int) -> SongData | None:
        return await load_mai_song_by_id_from_db(song_id)

    async def load_all_songs(self) -> dict[int, SongData]:
        return await load_mai_song_data_from_db()  # type: ignore[return-value]

    async def query_alias_exact(self, alias_lower: str) -> list[tuple[int, str]]:
        matched_aliases = (
            await MaiSongAlias.filter(alias__iexact=alias_lower).select_related("song")
        )
        results: list[tuple[int, str]] = []
        for alias_record in matched_aliases:
            song_id = alias_record.song.id  # type: ignore
            results.append((song_id, str(alias_record.alias)))
        return results

    async def load_alias_records(self) -> list[tuple[int, str]]:
        all_aliases = await MaiSongAlias.all().values("id", "song_id", "alias")
        records: list[tuple[int, str]] = []
        for alias_record in all_aliases:
            alias = alias_record.get("alias")
            if not alias:
                continue
            records.append((alias_record["song_id"], str(alias)))
        return records

    async def get_song_aliases_for_song_id(self, song_id: int) -> list[str]:
        db_aliases = await MaiSongAlias.filter(song_id=song_id).order_by(
            "priority", "id"
        ).values_list("alias", flat=True)
        return [str(alias) for alias in db_aliases if alias]

    async def get_song_with_difficulty(
        self,
        song_id: int,
        song_type: str = "standard",
        level_index: int = 3,
    ) -> dict | None:
        song_data = await load_mai_song_by_id_from_db(song_id)
        if not song_data:
            return None

        difficulties = song_data.difficulties
        type_difficulties = difficulties.get(song_type, [])

        target_difficulty = (
            type_difficulties[level_index]
            if level_index < len(type_difficulties)
            else None
        )

        return {
            "song_data": song_data,
            "target_difficulty": target_difficulty,
        }


class ChunithmSongQueryAdapter:
    game_code = "chunithm"

    def get_song_store(self) -> dict[int, SongData]:
        return plugin_data.chuni_song_data

    def get_song_index(self) -> dict[int, str]:
        return plugin_data.chuni_song_index

    def get_song_title(self, song_data: SongData) -> str:
        return str(getattr(song_data, "title", "") or "")

    async def get_song_by_id(self, song_id: int) -> SongData | None:
        return await load_chuni_song_by_id_from_db(song_id)

    async def load_all_songs(self) -> dict[int, SongData]:
        return await load_chuni_song_data_from_db()  # type: ignore[return-value]

    async def query_alias_exact(self, alias_lower: str) -> list[tuple[int, str]]:
        matched_aliases = (
            await ChuniSongAlias.filter(alias__iexact=alias_lower).select_related("song")
        )
        results: list[tuple[int, str]] = []
        for alias_record in matched_aliases:
            song_id = alias_record.song.id  # type: ignore
            results.append((song_id, str(alias_record.alias)))
        return results

    async def load_alias_records(self) -> list[tuple[int, str]]:
        all_aliases = await ChuniSongAlias.all().values("id", "song_id", "alias")
        records: list[tuple[int, str]] = []
        for alias_record in all_aliases:
            alias = alias_record.get("alias")
            if not alias:
                continue
            records.append((alias_record["song_id"], str(alias)))
        return records

    async def get_song_aliases_for_song_id(self, song_id: int) -> list[str]:
        db_aliases = await ChuniSongAlias.filter(song_id=song_id).order_by(
            "priority", "id"
        ).values_list("alias", flat=True)

        aliases: list[str] = []
        seen_alias_lower: set[str] = set()
        for a in db_aliases:
            if not a:
                continue
            s = str(a)
            low = s.lower()
            if low in seen_alias_lower:
                continue
            seen_alias_lower.add(low)
            aliases.append(s)

        return aliases

    async def get_song_with_difficulty(
        self,
        song_id: int,
        song_type: str = "standard",
        level_index: int = 3,
    ) -> dict | None:
        # chunithm 的难度附加逻辑不在当前 adapter 里实现（保持原有行为：返回 None）
        _ = (song_id, song_type, level_index)
        return None


# 适配器注册已迁移至各 domain 的 DomainAdapter 模块：
#   - domains/maimai/maimai_adapter.py  (MaimaiDomainAdapter)
#   - domains/chunithm/chunithm_adapter.py (ChunithmDomainAdapter)
# 旧 MaimaiSongQueryAdapter / ChunithmSongQueryAdapter 仍保留作为基类。


# 覆盖本模块对外导出：使用 shared 版本的查询/匹配核心
MatchType = SharedMatchType  # type: ignore
SongQueryResult = SharedSongQueryResult  # type: ignore

get_song_data = shared_get_song_data  # type: ignore
get_song_data_from_id = shared_get_song_data_from_id  # type: ignore
query_song_by_id = shared_query_song_by_id  # type: ignore
query_song_by_title_exact = shared_query_song_by_title_exact  # type: ignore
query_song_by_alias_exact = shared_query_song_by_alias_exact  # type: ignore
query_song_fuzzy = shared_query_song_fuzzy  # type: ignore
search_song = shared_search_song  # type: ignore
get_song_with_difficulty = shared_get_song_with_difficulty  # type: ignore
get_song_aliases = shared_get_song_aliases  # type: ignore
invalidate_alias_cache = shared_invalidate_alias_cache  # type: ignore
