"""Bot-wired song catalog facade for LXNS-backed game data."""

from __future__ import annotations

import asyncio
import traceback
from typing import Any

from arcade_helper import ArcadeHelperClient
from arcade_helper.storage.tortoise import TortoiseSongStore

from ...shared.game.adapter import DomainAdapter
from .plugin_data import plugin_data


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
        self.logger = logger
        self.auto_sync_enabled = auto_sync_enabled
        self.auto_sync_interval_seconds = max(60, int(auto_sync_interval_seconds))
        self.auto_sync_startup_delay_seconds = max(0, int(auto_sync_startup_delay_seconds))
        self.background_refresh_delay_seconds = max(0.0, float(background_refresh_delay_seconds))
        self._refresh_task: asyncio.Task[None] | None = None
        self._auto_sync_task: asyncio.Task[None] | None = None

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
        return await self.service.get_song_by_id(game_code, song_id)

    async def load_all_songs(self, game_code: str):
        return await self.service.load_all_songs(game_code)

    async def load_song_index(self, game_code: str) -> dict[int, str]:
        return await self.service.load_song_index(game_code)

    async def query_alias_exact(self, game_code: str, alias_lower: str) -> list[tuple[int, str]]:
        return await self.service.query_alias_exact(game_code, alias_lower)

    async def load_alias_records(self, game_code: str) -> list[tuple[int, str]]:
        return await self.service.load_alias_records(game_code)

    async def get_song_aliases_for_song_id(self, game_code: str, song_id: int) -> list[str]:
        return await self.service.get_song_aliases_for_song_id(game_code, song_id)

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
            self.service.invalidate_search_cache(game_code)
        except Exception as e:
            self.logger.warning(f"[{game_code}] 失效别名缓存失败（可忽略，下次 TTL 到期会自动刷新）: {e}")

    async def _sync_adapter_from_remote(self, adapter: DomainAdapter) -> bool:
        gc = adapter.game_code
        try:
            self.logger.info("=" * 50)
            self.logger.info(f"开始后台更新 {gc} 乐曲数据")
            self.logger.info("=" * 50)

            result = await self.service.sync_game_from_remote(
                gc,
                current_data_version=plugin_data.data_version if gc == "maimai" else None,
            )
            if result.status == "already_running":
                self.logger.info(f"{gc} 乐曲数据后台更新跳过：同步已在进行中")
                return False
            if not result.ok or result.songs is None:
                raise result.error or RuntimeError("catalog sync failed")
            if gc == "maimai":
                plugin_data.data_version = result.data_version
            setattr(
                plugin_data,
                self._song_index_attr(adapter),
                {song_id: song.title for song_id, song in result.songs.items()},
            )
            setattr(plugin_data, self._song_store_attr(adapter), {})
            adapter.clear_image_cache()
            self.invalidate_alias_cache(gc)
            self.logger.info(f"{gc} 乐曲数据后台更新完成")
            return True
        except Exception as e:
            traceback.print_exc()
            self.logger.error(f"后台更新 {gc} 乐曲数据失败，继续使用本地数据: {e}")
            return False

    async def sync_song_data_from_remote(self) -> None:
        adapters = self._domain_adapters()
        results = await asyncio.gather(*(self._sync_adapter_from_remote(adapter) for adapter in adapters))

        ok_count = sum(1 for ok in results if ok)
        if ok_count == len(results):
            self.logger.info("全部乐曲数据后台同步完成")
        elif ok_count:
            self.logger.warning("乐曲数据后台同步部分完成，失败的游戏继续使用本地数据")
        else:
            self.logger.warning("乐曲数据后台同步全部失败，继续使用本地数据")

    async def _run_background_refresh(self) -> None:
        await asyncio.sleep(self.background_refresh_delay_seconds)
        await self.sync_song_data_from_remote()

    def _on_refresh_task_done(self, task: asyncio.Task[None]) -> None:
        self._refresh_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            self.logger.warning("乐曲数据后台同步任务已取消")
        except Exception as e:
            self.logger.error(f"乐曲数据后台同步任务异常结束: {e}")

    def start_background_refresh(self) -> bool:
        if self._refresh_task and not self._refresh_task.done():
            return False

        self._refresh_task = asyncio.create_task(self._run_background_refresh())
        self._refresh_task.add_done_callback(self._on_refresh_task_done)
        return True

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
        started = self.start_background_refresh()
        if manual:
            self.start_auto_sync()

        if started:
            return local_available, f"{local_msg}；已启动后台同步"
        return local_available, f"{local_msg}；后台同步已在进行中"

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
        if not self._auto_sync_task or self._auto_sync_task.done():
            return
        self._auto_sync_task.cancel()
        try:
            await self._auto_sync_task
        except asyncio.CancelledError:
            self.logger.info("自动曲库同步任务已停止")
        finally:
            self._auto_sync_task = None


__all__ = ["BotCatalogClient"]
