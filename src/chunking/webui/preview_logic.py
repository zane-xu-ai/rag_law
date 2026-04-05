"""切分预览：汇总统计、相邻重叠、>15 段时的展示索引（纯函数，便于单测）。"""

from __future__ import annotations

import re

# 与 v01 文档一致：单次请求正文上限（字节，按 UTF-8 编码后计量）
MAX_PREVIEW_BYTES = 3 * 1024 * 1024


def overlap_between_adjacent(char_end_prev: int, char_start_next: int) -> int:
    """相邻两块在原文中的字符重叠长度（滑窗语义下一般为正）。"""
    if char_start_next >= char_end_prev:
        return 0
    return char_end_prev - char_start_next


def adjacent_overlaps(char_ranges: list[tuple[int, int]]) -> list[int]:
    """输入每块的 (char_start, char_end)，返回相邻对之间的重叠长度列表。"""
    out: list[int] = []
    for i in range(len(char_ranges) - 1):
        out.append(
            overlap_between_adjacent(char_ranges[i][1], char_ranges[i + 1][0])
        )
    return out


def source_paragraph_count(text: str) -> int:
    """按空行粗分「段落」数量，仅作参考，不参与切分。"""
    if not text.strip():
        return 0
    parts = re.split(r"\n\s*\n", text.strip())
    return sum(1 for p in parts if p.strip())


def pick_display_indices(total_chunks: int) -> list[int]:
    """
    块数 ≤ 15：返回全部下标；>15：前 5 + 中间 5 + 后 5（共 15 个下标，不重复）。
    中间 5 段：`mid_start = max(5, min(n - 10, n // 2 - 2))`，即 `mid_start..mid_start+4`。
    """
    n = total_chunks
    if n <= 0:
        return []
    if n <= 15:
        return list(range(n))
    first = list(range(5))
    last = list(range(n - 5, n))
    lo, hi = 5, n - 6
    mid_start = max(lo, min(hi - 4, n // 2 - 2))
    middle = list(range(mid_start, mid_start + 5))
    return first + middle + last


def section_for_display_index(original_index: int, total_chunks: int) -> str:
    """展示块在全文中的区域：first / middle / last / all（未截断时均为 all）。"""
    if total_chunks <= 15:
        return "all"
    if original_index < 5:
        return "first"
    if original_index >= total_chunks - 5:
        return "last"
    return "middle"
