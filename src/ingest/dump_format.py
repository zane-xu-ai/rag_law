"""将 ES chunk 格式化为导出文本：单行、块间空行、重叠段用中文着重号「【】」包裹。"""

from __future__ import annotations

from typing import Any

MARK_L = "【"
MARK_R = "】"


def single_line(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\n", " ")


def overlap_local(
    s: int,
    e: int,
    other_start: int,
    other_end: int,
) -> tuple[int, int] | None:
    """当前块 [s,e) 与邻块在原文中的重叠，转为相对当前块文本的下标。"""
    o0 = max(s, other_start)
    o1 = min(e, other_end)
    if o0 >= o1:
        return None
    return (o0 - s, o1 - s)


def annotate_chunk_line(
    text: str,
    char_start: int,
    char_end: int,
    prev_src: dict[str, Any] | None,
    next_src: dict[str, Any] | None,
) -> str:
    """在块文本上为与前一块、后一块的重叠加 `**`；再压成单行。"""
    regions: list[tuple[int, int]] = []
    if prev_src is not None:
        r = overlap_local(
            char_start,
            char_end,
            int(prev_src["char_start"]),
            int(prev_src["char_end"]),
        )
        if r is not None:
            regions.append(r)
    if next_src is not None:
        r = overlap_local(
            char_start,
            char_end,
            int(next_src["char_start"]),
            int(next_src["char_end"]),
        )
        if r is not None:
            regions.append(r)
    if not regions:
        return single_line(text)
    regions.sort()
    merged: list[tuple[int, int]] = []
    for lo, hi in regions:
        if lo >= hi:
            continue
        if merged and merged[-1][1] >= lo:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    n = len(text)
    merged = [(max(0, lo), min(hi, n)) for lo, hi in merged]
    merged = [(lo, hi) for lo, hi in merged if lo < hi]
    out = text
    for lo, hi in sorted(merged, reverse=True):
        mid = out[lo:hi].replace(MARK_R, "〉")
        out = out[:lo] + MARK_L + mid + MARK_R + out[hi:]
    return single_line(out)


def build_file_body(sources: list[dict[str, Any]]) -> str:
    """多块：每块一行，块之间空一行（两个换行）。"""
    lines: list[str] = []
    n = len(sources)
    for i, src in enumerate(sources):
        text = src.get("text") or ""
        cs = int(src["char_start"])
        ce = int(src["char_end"])
        prev_src = sources[i - 1] if i > 0 else None
        next_src = sources[i + 1] if i + 1 < n else None
        lines.append(annotate_chunk_line(text, cs, ce, prev_src, next_src))
    return "\n\n".join(lines) + "\n"
