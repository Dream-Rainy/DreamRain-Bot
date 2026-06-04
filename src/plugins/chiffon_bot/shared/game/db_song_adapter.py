"""Reusable DB-backed implementation for song-domain adapters."""

from __future__ import annotations

import traceback
from typing import Any, Mapping

from nonebot import logger

from ...integrations.lxns.plugin_data import plugin_data
from ..song_data import SongData


class DbSongAdapter:
    """Base class for games whose songs and aliases are stored in Tortoise models."""

    game_code: str
    display_name: str
    level_names: list[str]
    difficulty_types: list[str]
    temp_id_threshold: int
    song_store_attr: str
    song_index_attr: str
    supports_song_with_difficulty = False
    dedupe_aliases_for_display = False

    def get_db_song_model(self) -> type:
        raise NotImplementedError

    def get_db_alias_model(self) -> type:
        raise NotImplementedError

    def song_to_db_defaults(self, song: SongData) -> dict[str, Any]:
        raise NotImplementedError

    def song_from_db_row(self, row: Any, aliases: list[str]) -> SongData:
        raise NotImplementedError

    def get_song_store(self) -> Mapping[int, SongData]:
        return getattr(plugin_data, self.song_store_attr)

    def get_song_index(self) -> Mapping[int, str]:
        return getattr(plugin_data, self.song_index_attr)

    def get_song_title(self, song_data: SongData) -> str:
        return str(getattr(song_data, "title", "") or "")

    async def get_song_by_id(self, song_id: int) -> SongData | None:
        try:
            SongModel = self.get_db_song_model()
            AliasModel = self.get_db_alias_model()
            song = await SongModel.get_or_none(id=song_id)
            if song is None:
                return None
            aliases = await AliasModel.filter(song_id=song_id).order_by(
                "priority", "id"
            ).values_list("alias", flat=True)
            return self.song_from_db_row(song, [str(a) for a in aliases if a])
        except Exception as e:
            logger.error(f"[{self.game_code}] 从数据库加载乐曲 {song_id} 失败: {e}")
            traceback.print_exc()
            return None

    async def load_all_songs(self) -> dict[int, SongData]:
        logger.info(f"[{self.game_code}] 从数据库加载乐曲历史数据...")
        try:
            SongModel = self.get_db_song_model()
            AliasModel = self.get_db_alias_model()
            songs = await SongModel.all()
            if not songs:
                logger.warning(f"[{self.game_code}] 数据库中没有乐曲数据")
                return {}

            song_ids = [song.id for song in songs]
            aliases_by_song_id: dict[int, list[str]] = {sid: [] for sid in song_ids}
            alias_rows = (
                await AliasModel.filter(song_id__in=song_ids)
                .order_by("song_id", "priority", "id")
                .values("song_id", "alias")
            )
            for row in alias_rows:
                sid = row.get("song_id")
                alias = row.get("alias")
                if sid is not None and alias:
                    aliases_by_song_id.setdefault(sid, []).append(str(alias))

            return {
                song.id: self.song_from_db_row(song, aliases_by_song_id.get(song.id, []))
                for song in songs
            }
        except Exception as e:
            logger.error(f"[{self.game_code}] 从数据库加载乐曲数据失败: {e}")
            traceback.print_exc()
            return {}

    async def load_song_index_from_db(self) -> dict[int, str]:
        try:
            SongModel = self.get_db_song_model()
            rows = await SongModel.all().values("id", "title")
            return {
                int(row["id"]): str(row.get("title") or "")
                for row in rows
                if row.get("id") is not None
            }
        except Exception as e:
            logger.error(f"[{self.game_code}] 从数据库加载乐曲索引失败: {e}")
            traceback.print_exc()
            return {}

    async def query_alias_exact(self, alias_lower: str) -> list[tuple[int, str]]:
        AliasModel = self.get_db_alias_model()
        matched_aliases = await AliasModel.filter(
            alias__iexact=alias_lower
        ).select_related("song")
        return [
            (alias_record.song.id, str(alias_record.alias))  # type: ignore[attr-defined]
            for alias_record in matched_aliases
        ]

    async def load_alias_records(self) -> list[tuple[int, str]]:
        AliasModel = self.get_db_alias_model()
        all_aliases = await AliasModel.all().values("id", "song_id", "alias")
        records: list[tuple[int, str]] = []
        for alias_record in all_aliases:
            alias = alias_record.get("alias")
            if alias:
                records.append((alias_record["song_id"], str(alias)))
        return records

    async def get_song_aliases_for_song_id(self, song_id: int) -> list[str]:
        AliasModel = self.get_db_alias_model()
        db_aliases = await AliasModel.filter(song_id=song_id).order_by(
            "priority", "id"
        ).values_list("alias", flat=True)

        aliases: list[str] = []
        seen: set[str] = set()
        for alias in db_aliases:
            if not alias:
                continue
            text = str(alias)
            key = text.lower()
            if self.dedupe_aliases_for_display and key in seen:
                continue
            seen.add(key)
            aliases.append(text)
        return aliases

    async def get_song_with_difficulty(
        self,
        song_id: int,
        song_type: str = "standard",
        level_index: int = 3,
    ) -> dict | None:
        if not self.supports_song_with_difficulty:
            return None

        song_data = await self.get_song_by_id(song_id)
        if not song_data:
            return None

        type_difficulties = (song_data.difficulties or {}).get(song_type, [])
        target_difficulty = (
            type_difficulties[level_index]
            if level_index < len(type_difficulties)
            else None
        )
        return {
            "song_data": song_data,
            "target_difficulty": target_difficulty,
        }
