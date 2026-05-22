"""ma2 谱面文件解析器 — 解析 .ma2 文件提取 note 数量统计。

支持两种格式版本：
- 旧版 (≤ 1.03.00): note type 直接是 TAP/HLD/BRK/STR 等
- 新版 (≥ 1.04.00): note type 使用修饰符+基础类型，如 NMTAP/BRTAP/EXTAP
"""

from __future__ import annotations

import re
from pathlib import Path

# 新版格式正则: 修饰符(2字符) + 基础类型(TAP/HLD/TTP/THO/STR/S**)
_NEW_FORMAT_RE = re.compile(r"^(\w{2})(TAP|HLD|TTP|THO|STR|S(\w{2}))$")

# 旧版 note type → 分类映射
_OLD_BREAK_TYPES = frozenset({"BRK", "BST"})
_OLD_TAP_TYPES = frozenset({"TAP", "XTP", "STR", "XST"})
_OLD_HOLD_TYPES = frozenset({"HLD", "XHO", "THO"})
_OLD_TOUCH_TYPES = frozenset({"TTP"})

# ma2 文件头部关键字（非 note 数据行）
_HEADER_KEYWORDS = frozenset({
    "VERSION", "FES_MODE", "BPM_DEF", "MET_DEF",
    "RESOLUTION", "CLK_DEF", "COMPATIBLE_CODE",
    "BPM", "MET",
})

# 汇总行前缀（遇到即停止解析 note 数据）
_SUMMARY_PREFIXES = ("T_REC_", "T_NUM_", "T_JUDGE_", "TTM_")


class NoteCounts:
    """ma2 谱面 note 数量统计。"""

    def __init__(self) -> None:
        self.tap: int = 0
        self.hold: int = 0
        self.slide: int = 0
        self.touch: int = 0
        self.break_: int = 0

    @property
    def total(self) -> int:
        return self.tap + self.hold + self.slide + self.touch + self.break_

    def to_dict(self) -> dict[str, int]:
        return {
            "tap": self.tap,
            "hold": self.hold,
            "slide": self.slide,
            "touch": self.touch,
            "break": self.break_,
            "total": self.total,
        }


def _count_old_format(lines: list[str]) -> NoteCounts:
    """旧版格式 (≤ 1.03.00) 的 note 计数。"""
    counts = NoteCounts()
    for line in lines:
        note_type = line.split("\t")[0]
        if note_type in _OLD_BREAK_TYPES:
            counts.break_ += 1
        elif note_type in _OLD_TAP_TYPES:
            counts.tap += 1
        elif note_type in _OLD_HOLD_TYPES:
            counts.hold += 1
        elif note_type in _OLD_TOUCH_TYPES:
            counts.touch += 1
        elif note_type.startswith("S") and len(note_type) == 3:
            counts.slide += 1
    return counts


def _count_new_format(lines: list[str]) -> NoteCounts:
    """新版格式 (≥ 1.04.00) 的 note 计数。"""
    counts = NoteCounts()
    for line in lines:
        note_type = line.split("\t")[0]
        m = _NEW_FORMAT_RE.match(note_type)
        if not m:
            continue
        modifier = m.group(1)
        # BR/BX 修饰符 → Break（最高优先级）
        if modifier in ("BR", "BX"):
            counts.break_ += 1
            continue
        base_type = m.group(2)
        if base_type in ("TAP", "STR"):
            counts.tap += 1
        elif base_type in ("HLD", "THO"):
            counts.hold += 1
        elif base_type == "TTP":
            counts.touch += 1
        else:
            # 剩余的是 S** (Slide 变体)，但 CN 修饰符不计数
            if modifier != "CN":
                counts.slide += 1
    return counts


def parse_ma2(ma2_path: str | Path) -> NoteCounts:
    """解析 .ma2 文件，返回 note 数量统计。

    Args:
        ma2_path: .ma2 文件路径

    Returns:
        NoteCounts 实例（解析失败时所有计数为 0）
    """
    path = Path(ma2_path)
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return NoteCounts()

    raw_lines = content.strip().splitlines()

    # 提取 VERSION 行确定格式版本
    format_version = ""
    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("VERSION"):
            parts = line.split("\t")
            if len(parts) >= 3:
                format_version = parts[2]
            break

    # 收集 note 数据行（跳过头部、空行、汇总行）
    note_lines: list[str] = []
    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line:
            continue
        note_type = line.split("\t")[0]
        if note_type in _HEADER_KEYWORDS:
            continue
        if note_type.startswith(_SUMMARY_PREFIXES):
            break
        note_lines.append(line)

    # 根据版本选择计数方法
    is_new_format = format_version in ("1.04.00", "1.05.00")
    if is_new_format:
        return _count_new_format(note_lines)
    else:
        return _count_old_format(note_lines)
