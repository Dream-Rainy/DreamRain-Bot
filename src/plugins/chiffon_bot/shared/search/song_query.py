"""乐曲查询服务：支持 ID、标题、别名的模糊查询。

提供统一的查询接口，返回匹配的乐曲数据列表。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping
from collections import Counter
from time import monotonic
import unicodedata
from uuid import uuid4

import zhconv
from nonebot import logger
from pypinyin import Style, lazy_pinyin
from rapidfuzz import fuzz, process

from ..song_data import SongData
from ..game.registry import get_game_adapter

GameCode = str


class MatchType(Enum):
    """匹配类型枚举"""
    EXACT_ID = "exact_id"               # 精确 ID 匹配
    EXACT_TITLE = "exact_title"         # 精确标题匹配
    EXACT_ALIAS = "exact_alias"         # 精确别名匹配
    FUZZY_TITLE = "fuzzy_title"         # 模糊标题匹配
    FUZZY_ALIAS = "fuzzy_alias"         # 模糊别名匹配
    PINYIN_INITIALS = "pinyin_initials" # 拼音首字母精确匹配
    PINYIN_FULL = "pinyin_full"         # 完整拼音模糊匹配
    SIMPLIFIED = "simplified"           # 简体化归一后字面匹配


@dataclass(init=False)
class SongQueryResult:
    """查询结果数据类"""
    song_id: int
    title: str
    match_type: MatchType
    match_score: float  # 匹配分数 0-100
    matched_text: str   # 实际匹配到的文本
    song_data: SongData  # 由 adapter 注入的域模型

    def __init__(
        self,
        *,
        song_id: int,
        title: str,
        match_type: MatchType,
        match_score: float,
        matched_text: str,
        song_data: SongData,
    ) -> None:
        self.song_id = song_id
        self.title = title
        self.match_type = match_type
        self.match_score = match_score
        self.matched_text = matched_text
        self.song_data = song_data


# 模糊匹配阈值配置
FUZZY_THRESHOLD = 80  # 最低匹配分数
MAX_RESULTS = 10      # 最大返回结果数

# 置信度权重配置
TITLE_SCORE_BOOST = 1.15    # 标题匹配分数提升系数（提高 15%）
ALIAS_SCORE_PENALTY = 0.85  # 别名匹配分数惩罚系数（降低 15%）

# 短查询阈值调整
SHORT_QUERY_LENGTH = 2           # 短查询的字符数阈值
SHORT_QUERY_THRESHOLD_BOOST = 10 # 短查询的额外阈值提升

# 覆盖率截止参数
COVERAGE_HARD_CUTOFF = 0.15   # 低于此值直接丢弃
COVERAGE_SOFT_CUTOFF = 0.40   # 低于此值线性降级，高于此值保留原分

# CJK 复合分权重
CJK_RATIO_WEIGHT = 0.45
CJK_PARTIAL_WEIGHT = 0.20
CJK_DICE_WEIGHT = 0.35
ALIAS_CACHE_TTL_SECONDS = 300.0  # 别名表缓存时间（秒）

# 模块级拼音/简体化懒加载缓存
_pinyin_cache: dict[str, tuple[str, str]] = {}  # text → (initials, full_pinyin)
_simplified_cache: dict[str, str] = {}          # text → simplified_text
_normalized_cache: dict[str, str] = {}          # text → normalized_text
_alias_choices_cache_by_game: dict[str, dict[str, tuple[int, str]]] = {}
_alias_freq_cache_by_game: dict[str, Counter[str]] = {}
_alias_cache_loaded_at_by_game: dict[str, float] = {}


def _normalize_game_code(game_code: str) -> GameCode:
    return str(game_code).strip().lower()


def _song_store(game_code: str) -> Mapping[int, SongData]:
    adapter = get_game_adapter(_normalize_game_code(game_code))
    return adapter.get_song_store()


def _song_index(game_code: str) -> Mapping[int, str]:
    adapter = get_game_adapter(_normalize_game_code(game_code))
    return adapter.get_song_index()


async def _song_by_id(song_id: int, game_code: str) -> SongData | None:
    adapter = get_game_adapter(_normalize_game_code(game_code))
    return await adapter.get_song_by_id(song_id)


def _song_title(song_data: SongData, game_code: str) -> str:
    adapter = get_game_adapter(_normalize_game_code(game_code))
    return adapter.get_song_title(song_data)


def _is_cjk_char(char: str) -> bool:
    """判断字符是否为 CJK（中日韩）字符"""
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF or    # CJK 统一表意文字
        0x3400 <= code <= 0x4DBF or    # CJK 扩展 A
        0x20000 <= code <= 0x2A6DF or  # CJK 扩展 B
        0x2A700 <= code <= 0x2B73F or  # CJK 扩展 C
        0x2B740 <= code <= 0x2B81F or  # CJK 扩展 D
        0x2B820 <= code <= 0x2CEAF or  # CJK 扩展 E
        0x3040 <= code <= 0x309F or    # 平假名
        0x30A0 <= code <= 0x30FF or    # 片假名
        0xAC00 <= code <= 0xD7AF       # 韩文音节
    )


def _is_kanji(char: str) -> bool:
    """判断字符是否为 CJK 统一表意文字（汉字/漢字），不含假名"""
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF or
        0x3400 <= code <= 0x4DBF or
        0x20000 <= code <= 0x2A6DF or
        0x2A700 <= code <= 0x2B73F or
        0x2B740 <= code <= 0x2B81F or
        0x2B820 <= code <= 0x2CEAF
    )


def _has_cjk(text: str) -> bool:
    """判断文本是否包含 CJK 字符"""
    return any(_is_cjk_char(char) for char in text)


def _get_pinyin(text: str) -> tuple[str, str]:
    """返回文本的 (首字母缩写, 完整拼音)，懒加载缓存。

    - 汉字（不含假名）→ 取拼音首字母 / 无声调完整拼音
    - ASCII 字母 → 保留原样（小写）
    - 其余字符（假名、标点等）→ 跳过
    """
    if text in _pinyin_cache:
        return _pinyin_cache[text]

    initials_chars: list[str] = []
    full_chars: list[str] = []

    for char in text:
        if _is_kanji(char):
            first = lazy_pinyin(char, style=Style.FIRST_LETTER)
            full = lazy_pinyin(char, style=Style.NORMAL)
            if first:
                initials_chars.append(first[0].lower())
            if full:
                full_chars.append(full[0].lower())
        elif char.isascii() and char.isalpha():
            initials_chars.append(char.lower())
            full_chars.append(char.lower())

    result = ("".join(initials_chars), "".join(full_chars))
    _pinyin_cache[text] = result
    return result


def _normalize_to_simplified(text: str) -> str:
    """将文本中的繁体/日文汉字转换为简体中文，懒加载缓存。

    使用 zhconv 的 zh-hans 配置，平假名/片假名保持不变。
    """
    if text in _simplified_cache:
        return _simplified_cache[text]
    result = zhconv.convert(text, "zh-hans")
    _simplified_cache[text] = result
    return result


def _normalize_for_matching(text: str) -> str:
    """统一匹配归一化：NFKC + lower + 简体化 + 去常见分隔符。"""
    if text in _normalized_cache:
        return _normalized_cache[text]

    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = _normalize_to_simplified(normalized)
    separators = {" ", "\t", "\n", "\r", "　", "·", "・", "･", "-", "_"}
    normalized = "".join(ch for ch in normalized if ch not in separators)
    _normalized_cache[text] = normalized
    return normalized


def _get_fuzzy_scorer(query: str):
    """根据查询内容选择合适的模糊匹配算法"""
    if _has_cjk(query):
        if len(query) <= SHORT_QUERY_LENGTH:
            return fuzz.ratio
        return fuzz.partial_ratio
    return fuzz.WRatio


def _get_symmetric_coverage(query: str, matched_text: str) -> float:
    query_len = len(query)
    matched_len = len(matched_text)
    if query_len == 0 or matched_len == 0:
        return 0.0
    longer = max(query_len, matched_len)
    shorter = min(query_len, matched_len)
    return shorter / longer


def _apply_coverage_guard(score: float, query: str, matched_text: str) -> float:
    """基于对称覆盖率的分数保护，防止长短不对称误匹配。

    coverage = min(len(query), len(matched_text)) / max(len(query), len(matched_text))

    - query_len == 1：非完全匹配一律返回 0.0
    - coverage < COVERAGE_HARD_CUTOFF (0.15)：硬截止，返回 0.0
    - coverage in [0.15, 0.40)：线性降级
    - coverage >= 0.40：保留原始分数
    """
    query_len = len(query)
    matched_len = len(matched_text)

    if matched_len == 0:
        return 0.0

    if query_len == 1:
        return score if query.lower() == matched_text.lower() else 0.0

    coverage = _get_symmetric_coverage(query, matched_text)

    if coverage < COVERAGE_HARD_CUTOFF:
        return 0.0

    if coverage < COVERAGE_SOFT_CUTOFF:
        return score * (coverage / COVERAGE_SOFT_CUTOFF)

    return score


def _cjk_bigram_dice(a: str, b: str) -> float:
    """CJK 文本 2-gram Dice 系数，返回 0-100。"""
    if not a or not b:
        return 0.0
    if len(a) == 1 and len(b) == 1:
        return 100.0 if a == b else 0.0
    if len(a) < 2 or len(b) < 2:
        return 50.0 if a in b or b in a else 0.0

    a_bigrams = [a[i:i + 2] for i in range(len(a) - 1)]
    b_bigrams = [b[i:i + 2] for i in range(len(b) - 1)]
    inter = Counter(a_bigrams) & Counter(b_bigrams)
    inter_count = sum(inter.values())
    if inter_count == 0:
        return 0.0
    return (2.0 * inter_count / (len(a_bigrams) + len(b_bigrams))) * 100.0


def _compute_composite_score(query: str, candidate: str, raw_score: float) -> tuple[float, float, float, float]:
    """计算匹配复合分，返回 (composite, ratio, partial, dice)。"""
    if _has_cjk(query) or _has_cjk(candidate):
        ratio = fuzz.ratio(query, candidate)
        partial = fuzz.partial_ratio(query, candidate)
        dice = _cjk_bigram_dice(query, candidate)
        composite = (
            CJK_RATIO_WEIGHT * ratio
            + CJK_PARTIAL_WEIGHT * partial
            + CJK_DICE_WEIGHT * dice
        )
        return composite, ratio, partial, dice
    return raw_score, raw_score, raw_score, 0.0


def _alias_ambiguity_penalty(alias_norm: str, freq: int) -> float:
    """别名歧义惩罚：短别名与高频冲突别名降权。"""
    alias_len = len(alias_norm)
    if alias_len <= 1:
        return 0.0
    penalty = 1.0
    if alias_len == 2:
        penalty *= 0.75
    if freq >= 3:
        penalty *= 1.0 / (1.0 + 0.25 * (freq - 1))
    return penalty


def _get_effective_threshold(query_norm: str, base_threshold: float) -> float:
    """按归一化查询长度动态调整阈值。"""
    query_len = len(query_norm)
    if query_len <= 1:
        return max(base_threshold, 95.0)
    if query_len == 2:
        return max(base_threshold, 92.0)
    if query_len <= 4:
        return max(base_threshold, 86.0)
    return base_threshold


def _build_trace_id(query: str | int) -> str:
    q = str(query)
    q = q.replace("\n", " ").replace("\r", " ")
    q = q[:16]
    return f"{q}:{uuid4().hex[:8]}"


def invalidate_alias_cache(game_code: str | None = None) -> None:
    """失效别名缓存（曲库同步后调用）。"""
    global _alias_choices_cache_by_game, _alias_freq_cache_by_game, _alias_cache_loaded_at_by_game

    if game_code is None:
        _alias_choices_cache_by_game = {}
        _alias_freq_cache_by_game = {}
        _alias_cache_loaded_at_by_game = {}
        logger.debug("[alias_cache] invalidated (all games)")
        return

    gc = _normalize_game_code(game_code)
    _alias_choices_cache_by_game.pop(gc, None)
    _alias_freq_cache_by_game.pop(gc, None)
    _alias_cache_loaded_at_by_game.pop(gc, None)
    logger.debug(f"[alias_cache] invalidated game={gc}")


async def _get_alias_cache(
    game_code: str = "maimai",
    force_refresh: bool = False,
) -> tuple[dict[str, tuple[int, str]], Counter[str]]:
    gc = _normalize_game_code(game_code)
    now = monotonic()

    alias_choices_norm = _alias_choices_cache_by_game.get(gc)
    alias_freq = _alias_freq_cache_by_game.get(gc)
    loaded_at = _alias_cache_loaded_at_by_game.get(gc, 0.0)

    has_cache = bool(alias_choices_norm)
    cache_fresh = (
        not force_refresh
        and has_cache
        and (now - loaded_at) < ALIAS_CACHE_TTL_SECONDS
        and alias_freq is not None
    )

    if cache_fresh:
        logger.debug(
            f"[alias_cache][{gc}] hit entries={len(alias_choices_norm)} age={now - loaded_at:.1f}s"
        )
        return alias_choices_norm, alias_freq

    adapter = get_game_adapter(gc)
    alias_records = await adapter.load_alias_records()

    alias_choices_norm = {}
    alias_norm_list: list[str] = []

    for song_id, alias in alias_records:
        if not alias:
            continue
        alias_norm = _normalize_for_matching(str(alias))
        if not alias_norm:
            continue
        alias_norm_list.append(alias_norm)
        if alias_norm not in alias_choices_norm:
            alias_choices_norm[alias_norm] = (song_id, str(alias))

    alias_freq = Counter(alias_norm_list)
    _alias_choices_cache_by_game[gc] = alias_choices_norm
    _alias_freq_cache_by_game[gc] = alias_freq
    _alias_cache_loaded_at_by_game[gc] = now

    logger.debug(
        f"[alias_cache][{gc}] reload entries={len(alias_choices_norm)} total_rows={len(alias_norm_list)}"
    )
    return alias_choices_norm, alias_freq


def _strip_query_prefix_for_retry(query: str) -> str:
    """兜底重试用：剥离难度/版本前缀（白/紫/红/黄/绿/标/标准/dx）。"""
    prefixes = ("白", "紫", "红", "黄", "绿", "标" ,"标准", "dx")
    current = query.lstrip()
    original = current

    while current:
        lowered = current.lower()
        matched = False
        for prefix in prefixes:
            if lowered.startswith(prefix):
                current = current[len(prefix):].lstrip()
                matched = True
                break
        if not matched:
            break

    if not current:
        return ""
    return current if current != original else ""


def _log_match_decision(
    strategy: str,
    trace_id: str,
    query: str,
    candidate: str,
    raw_score: float,
    composite_score: float,
    guard_score: float,
    final_score: float,
    threshold: float,
    norm_query: str,
    norm_candidate: str,
    coverage: float,
    ratio: float,
    partial: float,
    dice: float,
    alias_freq: int = 0,
    reason: str = "",
) -> None:
    """输出结构化匹配日志，便于排查误匹配。"""
    decision = "ACCEPT" if final_score >= threshold else "REJECT"
    logger.debug(
        f"[fuzzy][trace={trace_id}] strategy={strategy} query={query!r} norm_query={norm_query!r} "
        f"candidate={candidate!r} norm_candidate={norm_candidate!r} raw={raw_score:.1f} "
        f"ratio={ratio:.1f} partial={partial:.1f} dice={dice:.1f} composite={composite_score:.1f} "
        f"coverage={coverage:.3f} alias_freq={alias_freq} guard={guard_score:.1f} final={final_score:.1f} "
        f"threshold={threshold:.1f} reason={reason or '-'} -> {decision}"
    )


def get_song_data_from_id(
    song_id: int,
    *,
    game_code: str = "maimai",
) -> SongData | None:
    """从本地曲库缓存中按 id 获取乐曲数据。

    纯领域能力：不依赖 OAuth/用户会话/绑定等平台功能。
    仅要求对应游戏曲库已由启动流程载入 plugin_data。
    """

    return _song_store(game_code).get(song_id)


def get_song_data(
    query_info: Any,
    *,
    game_code: str = "maimai",
) -> SongData | None:
    """解析查询入参并返回乐曲数据。

    当前仅支持 song id（int）；后续可以扩展：别名、关键字、模糊搜索等。
    """

    if isinstance(query_info, int):
        return get_song_data_from_id(query_info, game_code=game_code)
    return None


async def query_song_by_id(
    song_id: int,
    *,
    game_code: str = "maimai",
) -> SongQueryResult | None:
    """通过 ID 精确查询乐曲。

    Args:
        song_id: 乐曲 ID

    Returns:
        查询结果，未找到则返回 None
    """
    logger.debug(f"查询乐曲 ID: {song_id} (game={game_code})")
    song_data = await _song_by_id(song_id, game_code)
    if song_data:
        t = _song_title(song_data, game_code)
        logger.debug(f"找到乐曲: {t}")
        return SongQueryResult(
            song_id=song_id,
            title=t,
            match_type=MatchType.EXACT_ID,
            match_score=100.0,
            matched_text=str(song_id),
            song_data=song_data,
        )
    logger.debug(f"未找到乐曲 ID: {song_id}")
    return None


async def query_song_by_title_exact(
    title: str,
    *,
    game_code: str = "maimai",
) -> list[SongQueryResult]:
    """通过标题精确查询乐曲（不区分大小写）。

    Args:
        title: 乐曲标题

    Returns:
        匹配的乐曲列表
    """
    results = []
    title_lower = title.lower()
    index = _song_index(game_code)

    for song_id, song_title in index.items():
        if song_title.lower() == title_lower:
            song_data = await _song_by_id(song_id, game_code)
            if not song_data:
                continue
            results.append(SongQueryResult(
                song_id=song_id,
                title=song_title,
                match_type=MatchType.EXACT_TITLE,
                match_score=100.0,
                matched_text=song_title,
                song_data=song_data,
            ))

    return results


async def query_song_by_alias_exact(
    alias: str,
    *,
    game_code: str = "maimai",
) -> list[SongQueryResult]:
    """通过别名精确查询乐曲（不区分大小写）。

    Args:
        alias: 别名

    Returns:
        匹配的乐曲列表
    """
    results: list[SongQueryResult] = []
    alias_lower = alias.lower()

    adapter = get_game_adapter(game_code)
    matched_aliases = await adapter.query_alias_exact(alias_lower)
    for song_id, alias_original in matched_aliases:
        song_data = await _song_by_id(song_id, game_code)
        if not song_data:
            continue
        results.append(
            SongQueryResult(
                song_id=song_id,
                title=_song_title(song_data, game_code),
                match_type=MatchType.EXACT_ALIAS,
                match_score=100.0,
                matched_text=str(alias_original),
                song_data=song_data,
            )
        )

    return results


async def query_song_fuzzy(
    query: str,
    threshold: float = FUZZY_THRESHOLD,
    trace_id: str = "",
    *,
    game_code: str = "maimai",
) -> list[SongQueryResult]:
    """模糊查询乐曲（标题 + 别名 + 拼音 + 简体化归一）。"""
    results: list[SongQueryResult] = []
    seen_song_ids: set[int] = set()
    index = _song_index(game_code)
    phase_stats: dict[str, dict[str, int]] = {}

    def _bump_phase(phase: str, key: str) -> None:
        if phase not in phase_stats:
            phase_stats[phase] = {
                "candidates": 0,
                "accepted": 0,
                "reject_coverage": 0,
                "reject_ambiguity": 0,
                "reject_threshold": 0,
            }
        phase_stats[phase][key] += 1

    query_norm = _normalize_for_matching(query)
    scorer = _get_fuzzy_scorer(query_norm)
    effective_threshold = _get_effective_threshold(query_norm, threshold)
    query_is_ascii = query_norm.isascii() and not _has_cjk(query_norm)
    query_has_cjk = _has_cjk(query_norm)

    if trace_id:
        logger.debug(
            f"[fuzzy][trace={trace_id}] start query={query!r} norm_query={query_norm!r} "
            f"threshold={threshold:.1f} effective_threshold={effective_threshold:.1f} "
            f"scorer={getattr(scorer, '__name__', str(scorer))}"
        )

    # ── 1. 标题原文匹配 ───────────────────────────────────────────────────────
    title_choices_norm: dict[str, tuple[int, str]] = {}
    for song_id, title in index.items():
        if not title:
            continue
        title_norm = _normalize_for_matching(title)
        if title_norm and title_norm not in title_choices_norm:
            title_choices_norm[title_norm] = (song_id, title)

    if title_choices_norm and query_norm:
        title_matches = process.extract(
            query_norm,
            title_choices_norm.keys(),
            scorer=scorer,
            limit=MAX_RESULTS * 3,
            score_cutoff=effective_threshold,
        )
        for title_norm, raw_score, _ in title_matches:
            _bump_phase("title_raw", "candidates")
            song_id, title = title_choices_norm[title_norm]
            if song_id in seen_song_ids:
                continue
            song_data = await _song_by_id(song_id, game_code)
            if not song_data:
                continue

            composite, ratio, partial, dice = _compute_composite_score(query_norm, title_norm, raw_score)
            coverage = _get_symmetric_coverage(query_norm, title_norm)
            guard_score = _apply_coverage_guard(composite, query_norm, title_norm)
            final_score = min(guard_score * TITLE_SCORE_BOOST, 100.0)

            reason = ""
            if guard_score <= 0:
                reason = "coverage"
                _bump_phase("title_raw", "reject_coverage")
            elif final_score < threshold:
                reason = "threshold"
                _bump_phase("title_raw", "reject_threshold")
            else:
                _bump_phase("title_raw", "accepted")
                seen_song_ids.add(song_id)
                results.append(SongQueryResult(
                    song_id=song_id,
                    title=title,
                    match_type=MatchType.FUZZY_TITLE,
                    match_score=final_score,
                    matched_text=title,
                    song_data=song_data,
                ))

            _log_match_decision(
                strategy="title_raw",
                trace_id=trace_id,
                query=query,
                candidate=title,
                raw_score=raw_score,
                composite_score=composite,
                guard_score=guard_score,
                final_score=final_score,
                threshold=threshold,
                norm_query=query_norm,
                norm_candidate=title_norm,
                coverage=coverage,
                ratio=ratio,
                partial=partial,
                dice=dice,
                reason=reason,
            )

    # ── 2. 别名原文匹配 + 歧义惩罚 ───────────────────────────────────────────
    alias_choices_norm, alias_freq = await _get_alias_cache(game_code)

    if alias_choices_norm and query_norm:
        alias_matches = process.extract(
            query_norm,
            alias_choices_norm.keys(),
            scorer=scorer,
            limit=MAX_RESULTS * 4,
            score_cutoff=effective_threshold,
        )
        for alias_norm, raw_score, _ in alias_matches:
            _bump_phase("alias_raw", "candidates")
            song_id, original_alias = alias_choices_norm[alias_norm]
            if song_id in seen_song_ids:
                continue
            song_data = await _song_by_id(song_id, game_code)
            if not song_data:
                continue

            composite, ratio, partial, dice = _compute_composite_score(query_norm, alias_norm, raw_score)
            coverage = _get_symmetric_coverage(query_norm, alias_norm)
            guard_score = _apply_coverage_guard(composite, query_norm, alias_norm)
            ambiguity = _alias_ambiguity_penalty(alias_norm, alias_freq.get(alias_norm, 1))
            final_score = guard_score * ALIAS_SCORE_PENALTY * ambiguity

            reason = ""
            if ambiguity <= 0:
                reason = "ambiguity"
                _bump_phase("alias_raw", "reject_ambiguity")
            elif guard_score <= 0:
                reason = "coverage"
                _bump_phase("alias_raw", "reject_coverage")
            elif final_score < threshold:
                reason = "threshold"
                _bump_phase("alias_raw", "reject_threshold")
            else:
                _bump_phase("alias_raw", "accepted")
                seen_song_ids.add(song_id)
                results.append(SongQueryResult(
                    song_id=song_id,
                    title=_song_title(song_data, game_code),
                    match_type=MatchType.FUZZY_ALIAS,
                    match_score=final_score,
                    matched_text=original_alias,
                    song_data=song_data,
                ))

            _log_match_decision(
                strategy="alias_raw",
                trace_id=trace_id,
                query=query,
                candidate=original_alias,
                raw_score=raw_score,
                composite_score=composite,
                guard_score=guard_score,
                final_score=final_score,
                threshold=threshold,
                norm_query=query_norm,
                norm_candidate=alias_norm,
                coverage=coverage,
                ratio=ratio,
                partial=partial,
                dice=dice,
                alias_freq=alias_freq.get(alias_norm, 1),
                reason=reason,
            )

    # ── 3. 拼音匹配（仅 ASCII 查询）──────────────────────────────────────────
    if query_is_ascii and len(query_norm) >= 2:
        query_ascii = query_norm
        title_full_pinyin_norm: dict[str, tuple[int, str]] = {}

        for song_id, title in index.items():
            if not title or not _has_cjk(title):
                continue
            initials, full_py = _get_pinyin(title)
            initials_norm = _normalize_for_matching(initials)
            full_norm = _normalize_for_matching(full_py)

            if initials_norm and initials_norm == query_ascii and song_id not in seen_song_ids:
                _bump_phase("title_pinyin_initials", "candidates")
                coverage = _get_symmetric_coverage(query_ascii, initials_norm)
                final_score = 98.0
                reason = "" if final_score >= threshold else "threshold"
                if final_score >= threshold:
                    song_data = await _song_by_id(song_id, game_code)
                    if not song_data:
                        continue
                    _bump_phase("title_pinyin_initials", "accepted")
                    seen_song_ids.add(song_id)
                    results.append(SongQueryResult(
                        song_id=song_id,
                        title=title,
                        match_type=MatchType.PINYIN_INITIALS,
                        match_score=final_score,
                        matched_text=title,
                        song_data=song_data,
                    ))
                else:
                    _bump_phase("title_pinyin_initials", "reject_threshold")
                _log_match_decision(
                    strategy="title_pinyin_initials",
                    trace_id=trace_id,
                    query=query,
                    candidate=title,
                    raw_score=98.0,
                    composite_score=98.0,
                    guard_score=98.0,
                    final_score=final_score,
                    threshold=threshold,
                    norm_query=query_ascii,
                    norm_candidate=initials_norm,
                    coverage=coverage,
                    ratio=98.0,
                    partial=98.0,
                    dice=0.0,
                    reason=reason,
                )

            if full_norm and full_norm not in title_full_pinyin_norm:
                title_full_pinyin_norm[full_norm] = (song_id, title)

        if title_full_pinyin_norm:
            py_title_matches = process.extract(
                query_ascii,
                title_full_pinyin_norm.keys(),
                scorer=fuzz.partial_ratio,
                limit=MAX_RESULTS * 3,
                score_cutoff=effective_threshold,
            )
            for full_norm, raw_score, _ in py_title_matches:
                _bump_phase("title_pinyin_full", "candidates")
                song_id, title = title_full_pinyin_norm[full_norm]
                if song_id in seen_song_ids:
                    continue
                song_data = await _song_by_id(song_id, game_code)
                if not song_data:
                    continue
                composite, ratio, partial, dice = _compute_composite_score(query_ascii, full_norm, raw_score)
                coverage = _get_symmetric_coverage(query_ascii, full_norm)
                guard_score = _apply_coverage_guard(composite, query_ascii, full_norm)
                final_score = min(guard_score * TITLE_SCORE_BOOST, 100.0)

                reason = ""
                if guard_score <= 0:
                    reason = "coverage"
                    _bump_phase("title_pinyin_full", "reject_coverage")
                elif final_score < threshold:
                    reason = "threshold"
                    _bump_phase("title_pinyin_full", "reject_threshold")
                else:
                    _bump_phase("title_pinyin_full", "accepted")
                    seen_song_ids.add(song_id)
                    results.append(SongQueryResult(
                        song_id=song_id,
                        title=title,
                        match_type=MatchType.PINYIN_FULL,
                        match_score=final_score,
                        matched_text=title,
                        song_data=song_data,
                    ))
                _log_match_decision(
                    strategy="title_pinyin_full",
                    trace_id=trace_id,
                    query=query,
                    candidate=title,
                    raw_score=raw_score,
                    composite_score=composite,
                    guard_score=guard_score,
                    final_score=final_score,
                    threshold=threshold,
                    norm_query=query_ascii,
                    norm_candidate=full_norm,
                    coverage=coverage,
                    ratio=ratio,
                    partial=partial,
                    dice=dice,
                    reason=reason,
                )

        alias_full_pinyin_norm: dict[str, tuple[int, str]] = {}
        for alias_norm, (song_id, original_alias) in alias_choices_norm.items():
            if not _has_cjk(original_alias):
                continue
            initials, full_py = _get_pinyin(original_alias)
            initials_norm = _normalize_for_matching(initials)
            full_norm = _normalize_for_matching(full_py)

            if initials_norm and initials_norm == query_ascii and song_id not in seen_song_ids:
                _bump_phase("alias_pinyin_initials", "candidates")
                song_data = await _song_by_id(song_id, game_code)
                if not song_data:
                    continue
                ambiguity = _alias_ambiguity_penalty(alias_norm, alias_freq.get(alias_norm, 1))
                final_score = 95.0 * ALIAS_SCORE_PENALTY * ambiguity
                coverage = _get_symmetric_coverage(query_ascii, initials_norm)
                reason = ""
                if ambiguity <= 0:
                    reason = "ambiguity"
                    _bump_phase("alias_pinyin_initials", "reject_ambiguity")
                elif final_score < threshold:
                    reason = "threshold"
                    _bump_phase("alias_pinyin_initials", "reject_threshold")
                else:
                    _bump_phase("alias_pinyin_initials", "accepted")
                    seen_song_ids.add(song_id)
                    results.append(SongQueryResult(
                        song_id=song_id,
                        title=_song_title(song_data, game_code),
                        match_type=MatchType.PINYIN_INITIALS,
                        match_score=final_score,
                        matched_text=original_alias,
                        song_data=song_data,
                    ))
                _log_match_decision(
                    strategy="alias_pinyin_initials",
                    trace_id=trace_id,
                    query=query,
                    candidate=original_alias,
                    raw_score=95.0,
                    composite_score=95.0,
                    guard_score=95.0,
                    final_score=final_score,
                    threshold=threshold,
                    norm_query=query_ascii,
                    norm_candidate=initials_norm,
                    coverage=coverage,
                    ratio=95.0,
                    partial=95.0,
                    dice=0.0,
                    alias_freq=alias_freq.get(alias_norm, 1),
                    reason=reason,
                )

            if full_norm and full_norm not in alias_full_pinyin_norm:
                alias_full_pinyin_norm[full_norm] = (song_id, original_alias)

        if alias_full_pinyin_norm:
            py_alias_matches = process.extract(
                query_ascii,
                alias_full_pinyin_norm.keys(),
                scorer=fuzz.partial_ratio,
                limit=MAX_RESULTS * 4,
                score_cutoff=effective_threshold,
            )
            for full_norm, raw_score, _ in py_alias_matches:
                _bump_phase("alias_pinyin_full", "candidates")
                song_id, original_alias = alias_full_pinyin_norm[full_norm]
                if song_id in seen_song_ids:
                    continue
                song_data = await _song_by_id(song_id, game_code)
                if not song_data:
                    continue
                alias_norm = _normalize_for_matching(original_alias)
                ambiguity = _alias_ambiguity_penalty(alias_norm, alias_freq.get(alias_norm, 1))
                composite, ratio, partial, dice = _compute_composite_score(query_ascii, full_norm, raw_score)
                coverage = _get_symmetric_coverage(query_ascii, full_norm)
                guard_score = _apply_coverage_guard(composite, query_ascii, full_norm)
                final_score = guard_score * ALIAS_SCORE_PENALTY * ambiguity

                reason = ""
                if ambiguity <= 0:
                    reason = "ambiguity"
                    _bump_phase("alias_pinyin_full", "reject_ambiguity")
                elif guard_score <= 0:
                    reason = "coverage"
                    _bump_phase("alias_pinyin_full", "reject_coverage")
                elif final_score < threshold:
                    reason = "threshold"
                    _bump_phase("alias_pinyin_full", "reject_threshold")
                else:
                    _bump_phase("alias_pinyin_full", "accepted")
                    seen_song_ids.add(song_id)
                    results.append(SongQueryResult(
                        song_id=song_id,
                        title=_song_title(song_data, game_code),
                        match_type=MatchType.PINYIN_FULL,
                        match_score=final_score,
                        matched_text=original_alias,
                        song_data=song_data,
                    ))
                _log_match_decision(
                    strategy="alias_pinyin_full",
                    trace_id=trace_id,
                    query=query,
                    candidate=original_alias,
                    raw_score=raw_score,
                    composite_score=composite,
                    guard_score=guard_score,
                    final_score=final_score,
                    threshold=threshold,
                    norm_query=query_ascii,
                    norm_candidate=full_norm,
                    coverage=coverage,
                    ratio=ratio,
                    partial=partial,
                    dice=dice,
                    alias_freq=alias_freq.get(alias_norm, 1),
                    reason=reason,
                )

    # ── 4. 简体化归一匹配（仅含 CJK 查询，补充召回）──────────────────────────
    if query_has_cjk:
        query_simplified = _normalize_for_matching(_normalize_to_simplified(query_norm))
        simplified_scorer = _get_fuzzy_scorer(query_simplified)

        simplified_title_choices: dict[str, tuple[int, str]] = {}
        for song_id, title in index.items():
            if song_id in seen_song_ids:
                continue
            if not title or not _has_cjk(title):
                continue
            title_norm = _normalize_for_matching(title)
            simplified_norm = _normalize_for_matching(_normalize_to_simplified(title))
            if simplified_norm and simplified_norm != title_norm and simplified_norm not in simplified_title_choices:
                simplified_title_choices[simplified_norm] = (song_id, title)

        if simplified_title_choices and query_simplified:
            simp_title_matches = process.extract(
                query_simplified,
                simplified_title_choices.keys(),
                scorer=simplified_scorer,
                limit=MAX_RESULTS * 3,
                score_cutoff=effective_threshold,
            )
            for simp_norm, raw_score, _ in simp_title_matches:
                _bump_phase("title_simplified", "candidates")
                song_id, original_title = simplified_title_choices[simp_norm]
                if song_id in seen_song_ids:
                    continue
                song_data = await _song_by_id(song_id, game_code)
                if not song_data:
                    continue
                composite, ratio, partial, dice = _compute_composite_score(query_simplified, simp_norm, raw_score)
                coverage = _get_symmetric_coverage(query_simplified, simp_norm)
                guard_score = _apply_coverage_guard(composite, query_simplified, simp_norm)
                final_score = min(guard_score * TITLE_SCORE_BOOST, 100.0)

                reason = ""
                if guard_score <= 0:
                    reason = "coverage"
                    _bump_phase("title_simplified", "reject_coverage")
                elif final_score < threshold:
                    reason = "threshold"
                    _bump_phase("title_simplified", "reject_threshold")
                else:
                    _bump_phase("title_simplified", "accepted")
                    seen_song_ids.add(song_id)
                    results.append(SongQueryResult(
                        song_id=song_id,
                        title=original_title,
                        match_type=MatchType.SIMPLIFIED,
                        match_score=final_score,
                        matched_text=original_title,
                        song_data=song_data,
                    ))
                _log_match_decision(
                    strategy="title_simplified",
                    trace_id=trace_id,
                    query=query,
                    candidate=original_title,
                    raw_score=raw_score,
                    composite_score=composite,
                    guard_score=guard_score,
                    final_score=final_score,
                    threshold=threshold,
                    norm_query=query_simplified,
                    norm_candidate=simp_norm,
                    coverage=coverage,
                    ratio=ratio,
                    partial=partial,
                    dice=dice,
                    reason=reason,
                )

        simplified_alias_choices: dict[str, tuple[int, str]] = {}
        for alias_norm, (song_id, original_alias) in alias_choices_norm.items():
            if song_id in seen_song_ids:
                continue
            if not _has_cjk(original_alias):
                continue
            simplified_norm = _normalize_for_matching(_normalize_to_simplified(original_alias))
            if simplified_norm and simplified_norm != alias_norm and simplified_norm not in simplified_alias_choices:
                simplified_alias_choices[simplified_norm] = (song_id, original_alias)

        if simplified_alias_choices and query_simplified:
            simp_alias_matches = process.extract(
                query_simplified,
                simplified_alias_choices.keys(),
                scorer=simplified_scorer,
                limit=MAX_RESULTS * 4,
                score_cutoff=effective_threshold,
            )
            for simp_norm, raw_score, _ in simp_alias_matches:
                _bump_phase("alias_simplified", "candidates")
                song_id, original_alias = simplified_alias_choices[simp_norm]
                if song_id in seen_song_ids:
                    continue
                song_data = await _song_by_id(song_id, game_code)
                if not song_data:
                    continue
                alias_norm = _normalize_for_matching(original_alias)
                ambiguity = _alias_ambiguity_penalty(alias_norm, alias_freq.get(alias_norm, 1))
                composite, ratio, partial, dice = _compute_composite_score(query_simplified, simp_norm, raw_score)
                coverage = _get_symmetric_coverage(query_simplified, simp_norm)
                guard_score = _apply_coverage_guard(composite, query_simplified, simp_norm)
                final_score = guard_score * ALIAS_SCORE_PENALTY * ambiguity

                reason = ""
                if ambiguity <= 0:
                    reason = "ambiguity"
                    _bump_phase("alias_simplified", "reject_ambiguity")
                elif guard_score <= 0:
                    reason = "coverage"
                    _bump_phase("alias_simplified", "reject_coverage")
                elif final_score < threshold:
                    reason = "threshold"
                    _bump_phase("alias_simplified", "reject_threshold")
                else:
                    _bump_phase("alias_simplified", "accepted")
                    seen_song_ids.add(song_id)
                    results.append(SongQueryResult(
                        song_id=song_id,
                        title=_song_title(song_data, game_code),
                        match_type=MatchType.SIMPLIFIED,
                        match_score=final_score,
                        matched_text=original_alias,
                        song_data=song_data,
                    ))
                _log_match_decision(
                    strategy="alias_simplified",
                    trace_id=trace_id,
                    query=query,
                    candidate=original_alias,
                    raw_score=raw_score,
                    composite_score=composite,
                    guard_score=guard_score,
                    final_score=final_score,
                    threshold=threshold,
                    norm_query=query_simplified,
                    norm_candidate=simp_norm,
                    coverage=coverage,
                    ratio=ratio,
                    partial=partial,
                    dice=dice,
                    alias_freq=alias_freq.get(alias_norm, 1),
                    reason=reason,
                )

    for phase, stat in phase_stats.items():
        if trace_id:
            logger.debug(
                f"[fuzzy][trace={trace_id}] phase={phase} candidates={stat['candidates']} accepted={stat['accepted']} "
                f"reject_coverage={stat['reject_coverage']} reject_ambiguity={stat['reject_ambiguity']} "
                f"reject_threshold={stat['reject_threshold']}"
            )

    results.sort(key=lambda x: x.match_score, reverse=True)
    if trace_id:
        logger.debug(f"[fuzzy][trace={trace_id}] done results={len(results)}")
    return results[:MAX_RESULTS]


async def search_song(
    query: str | int,
    _prefix_retry: bool = True,
    _trace_id: str | None = None,
    *,
    game_code: str = "maimai",
) -> list[SongQueryResult]:
    """统一乐曲搜索入口。

    搜索优先级：
    1. 如果是整数，尝试 ID 精确匹配（命中即返回）
    2. 标题精确匹配（命中即返回，不再查别名）
    3. 别名精确匹配（命中即返回）
    4. 模糊匹配（标题 + 别名 + 拼音 + 简体化归一）

    Args:
        query: 查询字符串或乐曲 ID
        game_code: ``maimai`` 或 ``chunithm``

    Returns:
        匹配的乐曲列表（按相关性排序）
    """
    gc = _normalize_game_code(game_code)
    trace_id = _trace_id or _build_trace_id(query)
    logger.debug(
        f"[search][trace={trace_id}] game={gc} query={query!r} prefix_retry={_prefix_retry}"
    )

    # 1. 尝试 ID 匹配（如果是数字）
    if isinstance(query, int):
        result = await query_song_by_id(query, game_code=gc)
        if result:
            return [result]
    elif isinstance(query, str) and query.isdigit():
        result = await query_song_by_id(int(query), game_code=gc)
        if result:
            return [result]

    query_str = str(query).strip()
    if not query_str:
        return []

    # 2. 标题精确匹配（命中即返回，不再查别名）
    exact_title_results = await query_song_by_title_exact(query_str, game_code=gc)
    if exact_title_results:
        return exact_title_results

    # 3. 别名精确匹配
    exact_alias_results = await query_song_by_alias_exact(query_str, game_code=gc)
    if exact_alias_results:
        return exact_alias_results

    # 4. 模糊匹配
    fuzzy_results = await query_song_fuzzy(query_str, trace_id=trace_id, game_code=gc)
    if fuzzy_results:
        return fuzzy_results

    # 5. 无结果时兜底：剥离难度/版本前缀重试一次（避免误伤真实歌名）
    if _prefix_retry and isinstance(query, str):
        stripped_query = _strip_query_prefix_for_retry(query_str)
        if stripped_query:
            logger.debug(
                f"[search][trace={trace_id}] prefix_retry triggered "
                f"original={query_str!r} stripped={stripped_query!r}"
            )
            return await search_song(
                stripped_query,
                _prefix_retry=False,
                _trace_id=trace_id,
                game_code=gc,
            )

    return []


async def get_song_with_difficulty(
    song_id: int,
    song_type: str = "standard",
    level_index: int = 3,
    game_code: str = "maimai",
) -> dict | None:
    """获取乐曲数据并附加指定难度信息。

    Args:
        song_id: 乐曲 ID
        song_type: 谱面类型 ("standard" / "dx")
        level_index: 难度索引 (0=Basic, 1=Advanced, 2=Expert, 3=Master, 4=Re:Master)

    Returns:
        乐曲数据（包含 target_difficulty 字段）
    """
    gc = _normalize_game_code(game_code)
    adapter = get_game_adapter(gc)
    return await adapter.get_song_with_difficulty(
        song_id,
        song_type=song_type,
        level_index=level_index,
    )


async def get_song_aliases(
    song_query: str | int,
    *,
    game_code: str = "maimai",
) -> dict | None:
    """获取歌曲的所有别名。

    Args:
        song_query: 查询字符串或乐曲 ID
        game_code: ``maimai`` 或 ``chunithm``

    Returns:
        {
            "song_id": int,
            "title": str,
            "aliases": list[str]  # maimai: 含 LXNS/柚子查/dxrating；chunithm: 来自 DB 别名表或内存
        }
    """
    gc = _normalize_game_code(game_code)
    logger.debug(f"查询歌曲别名: {song_query} (game={gc})")

    results = await search_song(song_query, game_code=gc)

    if not results:
        logger.debug(f"未找到歌曲: {song_query}")
        return None

    result = results[0]
    song_id = result.song_id
    title = result.title

    adapter = get_game_adapter(gc)
    aliases = await adapter.get_song_aliases_for_song_id(song_id)

    logger.info(f"找到歌曲 [{song_id}] {title} 的 {len(aliases)} 个别名 (game={gc})")

    return {
        "song_id": song_id,
        "title": title,
        "aliases": aliases,
    }
