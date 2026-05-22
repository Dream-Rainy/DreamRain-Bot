from __future__ import annotations

from typing import Any, Iterable, Mapping, Protocol

from ..song_data import SongData


class SongQueryAdapter(Protocol):
    """
    多游戏差异适配器接口。

    shared 的搜索/模糊匹配核心只依赖这些方法，从而把游戏差异（曲库、别名来源、难度获取等）
    下沉到各 domain 实现。
    """

    # 规范化后的 game_code（例如：maimai/chunithm）
    game_code: str

    def get_song_store(self) -> Mapping[int, SongData]:
        """返回当前游戏完整曲库缓存（兼容旧调用点，新的查询链不应依赖它）。"""
        ...

    def get_song_index(self) -> Mapping[int, str]:
        """返回轻量曲库索引：song_id -> title。"""
        ...

    def get_song_title(self, song_data: SongData) -> str:
        """给定 song_data，提取标题字符串。"""
        ...

    async def get_song_by_id(self, song_id: int) -> SongData | None:
        """按 ID 从持久化存储加载完整乐曲数据。"""
        ...

    async def load_all_songs(self) -> Mapping[int, SongData]:
        """按需加载完整曲库；用于随机等需要遍历谱面的场景，不常驻缓存。"""
        ...

    async def query_alias_exact(self, alias_lower: str) -> list[tuple[int, str]]:
        """
        精确别名查询（不区分大小写）。

        Returns:
            list of (song_id, alias_original_text)
        """
        ...

    async def load_alias_records(self) -> Iterable[tuple[int, str]]:
        """
        加载全部别名记录（用于构建模糊别名缓存）。

        Returns:
            iterable of (song_id, alias_original_text)
        """
        ...

    async def get_song_aliases_for_song_id(self, song_id: int) -> list[str]:
        """获取单曲的全部别名（已按游戏规则去重/排序）。"""
        ...

    async def get_song_with_difficulty(
        self,
        song_id: int,
        song_type: str = "standard",
        level_index: int = 3,
    ) -> dict | None:
        """可选：获取带难度信息的乐曲数据。默认允许实现返回 None。"""
        ...


_adapters: dict[str, SongQueryAdapter] = {}


def register_game_adapter(game_code: str, adapter: SongQueryAdapter) -> None:
    gc = str(game_code).strip().lower()
    _adapters[gc] = adapter


def get_game_adapter(game_code: str) -> SongQueryAdapter:
    gc = str(game_code).strip().lower()
    adapter = _adapters.get(gc)
    if adapter is None:
        available = ", ".join(sorted(_adapters.keys())) or "-"
        raise KeyError(f"No song_query adapter for game_code={gc!r}. available={available}")
    return adapter


def invalidate_adapters() -> None:
    """仅用于测试/热加载时清理适配器。"""

    _adapters.clear()
