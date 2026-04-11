"""方案 C：嵌入相邻窗余弦相似度断点，再施加最小/最大块长约束（v1.1.7 设计备忘落地）。"""

from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from chunking.split import TextChunk, iter_text_slices
from conf.settings import project_root
from embeddings.base import EmbeddingBackend


def _cosine_dense(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


def _window_starts(text_len: int, window_chars: int, stride_chars: int) -> list[int]:
    if text_len <= 0:
        return []
    if text_len <= window_chars:
        return [0]
    out: list[int] = []
    s = 0
    while s + window_chars <= text_len:
        out.append(s)
        s += stride_chars
    last = text_len - window_chars
    if not out or out[-1] < last:
        out.append(last)
    return out


def raw_breakpoint_ranges(
    text_len: int,
    starts: list[int],
    adjacent_cosine: list[float],
    sim_threshold: float,
) -> list[tuple[int, int]]:
    """断点阶段、``min_chars`` 合并**之前**的区间：相邻窗余弦 ``< sim_threshold`` 处切开。"""
    if text_len <= 0:
        return []
    if len(starts) == 1:
        return [(0, text_len)]
    if len(adjacent_cosine) != len(starts) - 1:
        raise ValueError("adjacent_cosine 长度须为 len(starts)-1")

    boundaries = [0]
    for i in range(len(starts) - 1):
        if adjacent_cosine[i] < sim_threshold:
            bp = starts[i + 1]
            if bp > boundaries[-1]:
                boundaries.append(bp)
    if boundaries[-1] != text_len:
        boundaries.append(text_len)
    return [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]


def compute_adjacent_window_cosines(
    full_text: str,
    embedder: EmbeddingBackend,
    *,
    window_chars: int,
    stride_chars: int,
) -> dict[str, Any]:
    """全文只编码一次；返回 ``starts`` 与相邻窗余弦，供多次尝试不同 ``sim_threshold`` 而无需重复 embed。"""
    n = len(full_text)
    starts = _window_starts(n, window_chars, stride_chars)
    adjacent: list[float] = []
    if len(starts) <= 1:
        return {"text_len": n, "starts": starts, "adjacent_cosine": adjacent}
    windows = [full_text[s : s + window_chars] for s in starts]
    vecs = embedder.embed_documents(windows)
    if len(vecs) != len(windows):
        raise RuntimeError("embed_documents 条数与窗数不一致")
    for i in range(len(starts) - 1):
        adjacent.append(_cosine_dense(vecs[i], vecs[i + 1]))
    return {"text_len": n, "starts": starts, "adjacent_cosine": adjacent}


def adjacent_cosine_percentiles(
    adjacent_cosine: list[float],
    *,
    percentiles: tuple[float, ...] = (5.0, 10.0, 25.0, 50.0, 75.0, 90.0, 95.0),
) -> dict[str, float]:
    """相邻余弦的经验分位数（线性插值），用于选手动阈值。"""
    if not adjacent_cosine:
        return {}
    xs = sorted(adjacent_cosine)
    m = len(xs)
    out: dict[str, float] = {"count": float(m), "min": xs[0], "max": xs[-1], "mean": sum(xs) / m}
    for p in percentiles:
        if m == 1:
            v = xs[0]
        else:
            rk = (m - 1) * (p / 100.0)
            lo = int(math.floor(rk))
            hi = int(math.ceil(rk))
            if lo == hi:
                v = xs[lo]
            else:
                v = xs[lo] * (hi - rk) + xs[hi] * (rk - lo)
        out["p%.0f" % p] = v
    return out


def breakpoint_pipeline_stages(
    full_text: str,
    pack: dict[str, Any],
    *,
    sim_threshold: float,
    min_chars: int,
    max_chars: int,
    split_overlap: int,
) -> dict[str, Any]:
    """给定预计算的 ``compute_adjacent_window_cosines`` 结果，返回三阶段区间：原始断点 / min 合并后 / max 劈分后。"""
    n = int(pack["text_len"])
    starts = pack["starts"]
    adjacent = pack["adjacent_cosine"]
    raw = raw_breakpoint_ranges(n, starts, adjacent, sim_threshold)
    merged = _merge_ranges_min_len(raw, min_chars)
    final_ranges: list[tuple[int, int]] = []
    for s, e in merged:
        final_ranges.extend(_split_range_max_len(full_text, s, e, max_chars, split_overlap))
    return {
        "raw_ranges": raw,
        "merged_ranges": merged,
        "final_ranges": final_ranges,
    }


def _merge_ranges_min_len(
    ranges: list[tuple[int, int]],
    min_chars: int,
) -> list[tuple[int, int]]:
    """相邻区间向前合并，直到当前段长度 ≥ min_chars 或已无后继。"""
    if not ranges:
        return []
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(ranges):
        s, e = ranges[i]
        j = i
        while e - s < min_chars and j + 1 < len(ranges):
            j += 1
            e = ranges[j][1]
        out.append((s, e))
        i = j + 1
    return out


def _split_range_max_len(
    full_text: str,
    s: int,
    e: int,
    max_chars: int,
    overlap: int,
) -> list[tuple[int, int]]:
    piece = full_text[s:e]
    n = len(piece)
    if n <= max_chars:
        return [(s, e)]
    out: list[tuple[int, int]] = []
    for seg, rel0, rel1 in iter_text_slices(piece, max_chars, overlap):
        out.append((s + rel0, s + rel1))
    return out


def _merged_breakpoint_ranges(
    full_text: str,
    embedder: EmbeddingBackend,
    *,
    window_chars: int,
    stride_chars: int,
    sim_threshold: float,
    min_chars: int,
) -> tuple[list[tuple[int, int]], list[float], int]:
    """嵌入相似度断点 → 合并过短段。返回 (合并后区间, 相邻窗余弦列表, 合并前区间数)。"""
    pack = compute_adjacent_window_cosines(
        full_text,
        embedder,
        window_chars=window_chars,
        stride_chars=stride_chars,
    )
    n = int(pack["text_len"])
    starts = pack["starts"]
    adjacent_sims = pack["adjacent_cosine"]
    raw = raw_breakpoint_ranges(n, starts, adjacent_sims, sim_threshold)
    n_before_merge = len(raw)
    merged = _merge_ranges_min_len(raw, min_chars)
    return merged, adjacent_sims, n_before_merge


def breakpoint_embed_diagnostics_from_pack(
    pack: dict[str, Any],
    *,
    sim_threshold: float,
    min_chars: int,
    max_chars: int,
) -> dict[str, Any]:
    """基于 ``compute_adjacent_window_cosines`` 的缓存结果做诊断，**不重复 embed**。"""
    n = int(pack["text_len"])
    if n == 0:
        return {
            "text_chars": 0,
            "window_count": 0,
            "adjacent_cosine": [],
            "cosine_min": None,
            "cosine_max": None,
            "cosine_mean": None,
            "edges_below_threshold": 0,
            "ranges_before_merge": 0,
            "merged_range_count": 0,
            "only_max_chars_split": False,
            "max_chars_slices_est": 0,
        }
    starts = pack["starts"]
    adjacent_sims: list[float] = pack["adjacent_cosine"]
    raw = raw_breakpoint_ranges(n, starts, adjacent_sims, sim_threshold)
    n_before_merge = len(raw)
    merged = _merge_ranges_min_len(raw, min_chars)

    if adjacent_sims:
        cmin = min(adjacent_sims)
        cmax = max(adjacent_sims)
        cmean = sum(adjacent_sims) / len(adjacent_sims)
    else:
        cmin = cmax = cmean = None
    below = sum(1 for s in adjacent_sims if s < sim_threshold)

    only_one_span = len(merged) == 1 and merged[0][0] == 0 and merged[0][1] == n
    est_slices = 0
    for s, e in merged:
        piece_len = e - s
        if piece_len <= max_chars:
            est_slices += 1
        else:
            step = max_chars
            est_slices += (piece_len + step - 1) // step

    degenerate = bool(only_one_span and n > max_chars)

    return {
        "text_chars": n,
        "window_count": len(starts),
        "adjacent_cosine": adjacent_sims,
        "cosine_min": cmin,
        "cosine_max": cmax,
        "cosine_mean": cmean,
        "edges_below_threshold": below,
        "ranges_before_merge": n_before_merge,
        "merged_range_count": len(merged),
        "only_max_chars_split": degenerate,
        "max_chars_slices_est": est_slices,
    }


def breakpoint_embed_diagnostics(
    full_text: str,
    embedder: EmbeddingBackend,
    *,
    window_chars: int = 256,
    stride_chars: int = 128,
    sim_threshold: float = 0.72,
    min_chars: int = 200,
    max_chars: int = 2200,
) -> dict[str, Any]:
    """说明当前参数下断点阶段是否起作用，是否会**退化为仅靠 max_chars 字符滑窗**。

    当相邻滑动窗的余弦相似度**全程不低于** ``sim_threshold`` 时，相似度阶段不会在文内切开，
    合并后往往只剩一个 ``(0, n)``；若 ``n > max_chars``，最终块长会**看起来像**按 ``max_chars`` 固定切分。
    """
    n = len(full_text)
    if n == 0:
        return breakpoint_embed_diagnostics_from_pack(
            {"text_len": 0, "starts": [], "adjacent_cosine": []},
            sim_threshold=sim_threshold,
            min_chars=min_chars,
            max_chars=max_chars,
        )
    pack = compute_adjacent_window_cosines(
        full_text,
        embedder,
        window_chars=window_chars,
        stride_chars=stride_chars,
    )
    return breakpoint_embed_diagnostics_from_pack(
        pack,
        sim_threshold=sim_threshold,
        min_chars=min_chars,
        max_chars=max_chars,
    )


def iter_breakpoint_chunks_for_text(
    full_text: str,
    *,
    source_file: str,
    source_path: str | None,
    embedder: EmbeddingBackend,
    window_chars: int = 256,
    stride_chars: int = 128,
    sim_threshold: float = 0.72,
    min_chars: int = 200,
    max_chars: int = 2200,
    split_overlap: int = 0,
) -> Iterator[TextChunk]:
    """在重叠字窗上批量编码，相邻窗余弦低于阈值处记断点，再合并过短块、按滑窗劈开过长块。

    与 v1.1.7 方案 C 一致：断点由 **BGE 与相邻窗** 决定；``max_chars`` 过大段再退回字符滑窗。
    二次劈分默认 ``split_overlap=0``，相邻块 **无字面重叠**，导出文件去掉分隔条后与原文一致；若需与入库滑窗一致可显式传入正重叠（此时拼接导出会重复重叠区）。
    """
    n = len(full_text)
    if n == 0:
        return
    sid = source_path or source_file
    merged, _, _ = _merged_breakpoint_ranges(
        full_text,
        embedder,
        window_chars=window_chars,
        stride_chars=stride_chars,
        sim_threshold=sim_threshold,
        min_chars=min_chars,
    )

    final_ranges: list[tuple[int, int]] = []
    for s, e in merged:
        final_ranges.extend(_split_range_max_len(full_text, s, e, max_chars, split_overlap))

    for idx, (cs, ce) in enumerate(final_ranges):
        yield TextChunk(
            text=full_text[cs:ce],
            source_file=source_file,
            chunk_index=idx,
            char_start=cs,
            char_end=ce,
            source_path=source_path,
            source_id=sid,
            extra={"chunking": "breakpoint_embed_c", "sim_threshold": sim_threshold},
        )


def export_breakpoint_chunks_dir(
    md_paths: list[Path],
    out_dir: Path,
    embedder: EmbeddingBackend,
    *,
    window_chars: int = 256,
    stride_chars: int = 128,
    sim_threshold: float = 0.72,
    min_chars: int = 200,
    max_chars: int = 2200,
    split_overlap: int = 0,
    chunk_separator: str | None = None,
    progress: bool = True,
) -> list[Path]:
    """将若干 .md 按方案 C 切分并写入 ``out_dir/<basename>.md``，块之间插入 ``chunk_separator``。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sep = chunk_separator if chunk_separator is not None else default_chunk_separator()
    written: list[Path] = []
    root = project_root()
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None  # type: ignore[misc, assignment]
    use_bar = bool(progress and tqdm is not None)
    path_iter = (
        tqdm(md_paths, desc="c03 breakpoint", unit="file")
        if use_bar
        else md_paths
    )
    for md in path_iter:
        p = Path(md)
        if use_bar and hasattr(path_iter, "set_postfix_str"):
            path_iter.set_postfix_str(p.name[:48] + ("…" if len(p.name) > 48 else ""))
        text = p.read_text(encoding="utf-8")
        try:
            sp = p.resolve().relative_to(root).as_posix()
        except ValueError:
            sp = p.name
        chunks = list(
            iter_breakpoint_chunks_for_text(
                text,
                source_file=p.name,
                source_path=sp,
                embedder=embedder,
                window_chars=window_chars,
                stride_chars=stride_chars,
                sim_threshold=sim_threshold,
                min_chars=min_chars,
                max_chars=max_chars,
                split_overlap=split_overlap,
            )
        )
        bodies: list[str] = []
        for i, c in enumerate(chunks):
            if i > 0:
                bodies.append(sep)
            bodies.append(c.text)
        dest = out / p.name
        dest.write_text("".join(bodies), encoding="utf-8")
        written.append(dest)
    return written


def default_chunk_separator() -> str:
    """块与块之间极醒目分隔（纯文本，便于肉眼与 diff）。"""
    bar = "#" * 88
    return (
        "\n\n"
        + bar
        + "\n"
        + "##>>> CHUNK_BOUNDARY (breakpoint_embed C) <<<##\n"
        + bar
        + "\n\n"
    )
