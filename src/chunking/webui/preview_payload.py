"""由 ``TextChunk`` 列表构造与滑窗预览一致外形的 ``summary`` / ``display``（无 app 依赖，供多入口复用）。"""

from __future__ import annotations

from chunking.split import TextChunk
from chunking.webui.preview_logic import (
    adjacent_overlaps,
    pick_display_indices,
    section_for_display_index,
    source_paragraph_count,
)


def agg_ints(nums: list[int]) -> dict | None:
    if not nums:
        return None
    return {"min": min(nums), "max": max(nums), "avg": round(sum(nums) / len(nums), 2)}


def chunks_to_single_preview(text: str, chunks: list[TextChunk], *, summary: dict) -> dict:
    """由已切好的 ``TextChunk`` 列表生成与滑窗预览相同外形的 ``summary`` + ``display``。"""
    n = len(chunks)
    ranges = [(c.char_start, c.char_end) for c in chunks]
    overlaps = adjacent_overlaps(ranges)
    lengths = [len(c.text) for c in chunks]
    summary_out = {
        **summary,
        "total_chars": len(text),
        "chunk_count": n,
        "chars_per_chunk": lengths,
        "chars_per_chunk_stats": agg_ints(lengths),
        "overlap_between_adjacent": overlaps,
        "overlap_adjacent_stats": agg_ints(overlaps) if overlaps else None,
        "source_paragraphs": source_paragraph_count(text),
    }

    if n == 0:
        display = {
            "mode": "full",
            "total_chunks": 0,
            "omitted_message": None,
            "chunks": [],
        }
        return {"mode": "single", "summary": summary_out, "display": display}

    mode = "full" if n <= 15 else "truncated"
    indices = pick_display_indices(n)
    display_chunks: list[dict] = []
    for i in indices:
        c = chunks[i]
        overlap_prev = overlaps[i - 1] if i > 0 else 0
        overlap_next = overlaps[i] if i < n - 1 else 0
        display_chunks.append(
            {
                "index": c.chunk_index,
                "text": c.text,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "section": section_for_display_index(i, n),
                "overlap_prev": overlap_prev,
                "overlap_next": overlap_next,
            }
        )

    omitted_message: str | None = None
    if mode == "truncated":
        omitted_message = (
            f"共 {n} 段，仅展示前 5、中间 5、后 5 段（共 15 段），其余已省略。"
        )

    display = {
        "mode": mode,
        "total_chunks": n,
        "omitted_message": omitted_message,
        "chunks": display_chunks,
    }
    return {"mode": "single", "summary": summary_out, "display": display}
