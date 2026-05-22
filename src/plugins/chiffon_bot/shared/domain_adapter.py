"""游戏域适配器协议 — 扩展 SongQueryAdapter 加入同步、渲染、常量。

每个游戏 domain 实现此协议后，即可通过通用中间层获得完整的
查询 / 同步 / 命令注册 / 数据更新 能力。
"""

from __future__ import annotations

from typing import Any, Protocol

from .song_data import SongData
from .search.song_query_adapter import SongQueryAdapter


class DomainAdapter(SongQueryAdapter, Protocol):
    """完整游戏域适配器。

    继承 ``SongQueryAdapter`` 的全部查询接口，并新增：
    - 游戏常量（level_names, difficulty_types, display_name）
    - 数据同步（DB 模型映射、defaults 构建、行→模型转换）
    - 渲染（render / clear_cache）
    - 可选钩子（fetch_collections, fetch_raw_data）
    """

    # ── 游戏常量 ──
    display_name: str
    """UI 展示名，如 ``"maimai"`` / ``"CHUNITHM"``。"""

    level_names: list[str]
    """难度等级名称列表，如 ``["Basic","Advanced","Expert","Master","Re:Master"]``。"""

    difficulty_types: list[str]
    """谱面类型列表，如 ``["standard","dx"]`` / ``["standard","ultima"]``。"""

    # ── 数据同步 ──
    temp_id_threshold: int
    """临时 ID 阈值。同步前会删除 id >= 此值的脏数据。"""

    def get_db_song_model(self) -> type:
        """返回该游戏对应的 Tortoise ORM 乐曲模型类（如 ``MaiSong`` / ``ChuniSong``）。"""
        ...

    def get_db_alias_model(self) -> type:
        """返回该游戏对应的 Tortoise ORM 别名模型类（如 ``MaiSongAlias`` / ``ChuniSongAlias``）。"""
        ...

    def song_to_db_defaults(self, song: SongData) -> dict[str, Any]:
        """将 SongData 子类实例转换为 DB ``update_or_create`` 的 defaults 字典。"""
        ...

    def song_from_db_row(self, row: Any, aliases: list[str]) -> SongData:
        """将 DB 查询行 + 别名列表转换为 SongData 子类实例。"""
        ...

    # ── 渲染 ──
    async def render_song_image(self, song_data: SongData) -> bytes:
        """渲染歌曲信息图片，返回 PNG 字节。"""
        ...

    def clear_image_cache(self) -> None:
        """清除该游戏的图片渲染缓存。"""
        ...

    # ── 可选钩子 ──
    async def fetch_collections(self, song_id: int) -> list[dict[str, Any]]:
        """拉取单曲收藏信息（奖杯、称号等）。无此功能的游戏返回空列表。"""
        ...

    async def fetch_raw_data(self) -> dict[int, SongData]:
        """从外部 API 拉取并合并该游戏的完整曲库数据。

        Returns:
            {song_id: SongData 子类实例} 曲库字典。
        """
        ...


# ── 全局 DomainAdapter 注册表 ──
# 复用 SongQueryAdapter 的注册机制（DomainAdapter IS-A SongQueryAdapter）。
# 外部通过 get_domain_adapter(game_code) 获取完整适配器。

from .search.song_query_adapter import get_game_adapter as _get_query_adapter


def get_domain_adapter(game_code: str) -> DomainAdapter:
    """按 game_code 获取已注册的 ``DomainAdapter``。"""
    adapter = _get_query_adapter(game_code)
    if not isinstance(adapter, DomainAdapter):
        available = "maimai, chunithm"
        raise TypeError(
            f"Adapter for {game_code!r} is not a DomainAdapter "
            f"(got {type(adapter).__name__}). Available: {available}"
        )
    return adapter
