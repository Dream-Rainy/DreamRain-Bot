"""搜索结果消息构建工具。

提供两个辅助函数，供 maimai 和 chunithm 的 song_info handler 共用，
消除两处几乎相同的"找不到/多模糊结果列表/命中后提示"逻辑。
"""

from __future__ import annotations

from ..bot_response import BotResponse
from ..song_data import SongData
from .song_query import SongQueryResult


def _get_artist(song_data: SongData) -> str:
    """从 SongData 子类实例中提取曲师名。"""
    artist = getattr(song_data, "artist", None)
    return str(artist or "").strip()


def _result_label(r: SongQueryResult, *, show_artist: bool = True) -> str:
    """生成结果条目的显示标签；show_artist=True 时附加曲师。"""
    base = f"[{r.song_id}] {r.title}"
    if show_artist:
        artist = _get_artist(r.song_data)
        if artist:
            return f"{base}  {artist}"
    return base


def build_fuzzy_list_message(
    results: list[SongQueryResult],
    message_id: int,
    not_found_text: str = "未找到该乐曲",
) -> BotResponse | None:
    """根据查询结果决定是否提前返回消息。

    - 结果为空 → 返回"未找到"消息。
    - 无完全匹配且有多个模糊结果 → 返回模糊列表消息（附曲师）。
    - 其他情况（可继续渲染）→ 返回 None。
    """
    if not results:
        return BotResponse(text=not_found_text, reply_to=message_id)

    perfect = [r for r in results if r.match_score == 100.0]

    if len(perfect) == 0 and len(results) > 1:
        lines = ["找到多个近似结果，请使用更精确的关键词或 ID 查询：\n"]
        for result in results[:5]:
            lines.append(f"{_result_label(result)} ({result.match_score:.0f}%)")
        if len(results) > 5:
            lines.append(f"...还有 {len(results) - 5} 个结果")
        return BotResponse(text="\n".join(lines), reply_to=message_id)

    return None


def build_match_hint_text(
    perfect: list[SongQueryResult],
    fuzzy: list[SongQueryResult],
) -> str | None:
    """构建渲染图之后追加的提示文本。

    - 多个完全匹配：列出其余项（附曲师，便于同标题多曲区分）。
    - 唯一完全匹配但存在模糊结果：简短提示其他近似结果。
    - 其他情况：返回 None。
    """
    if len(perfect) > 1:
        lines = [f"找到 {len(perfect)} 个完全匹配，已显示权重最高的结果，其他匹配："]
        for r in perfect[1:]:
            lines.append(_result_label(r))
        return "\n".join(lines)

    if len(perfect) == 1 and fuzzy:
        other = "、".join(_result_label(r, show_artist=False) for r in fuzzy[:3])
        return f"其他近似结果：{other}"

    return None
