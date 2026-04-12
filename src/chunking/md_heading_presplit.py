"""v1.1.10：Markdown ATX 标题递归预切分，再对超长叶子做方案 D。

见 doc/plan/v1.1.10-md-heading-presolve-scheme-d.md。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

from chunking.document_segmentation import (
    infer_raw_ranges_from_pipeline,
    iter_document_segmentation_chunks_for_text,
)
from chunking.split import TextChunk
from conf.settings import project_root

_ATX = re.compile(r"^[ \t]{0,3}(#{1,6})(?:\s|$)")


def parse_atx_heading_spans(text: str) -> list[tuple[int, int]]:
    """扫描全文，返回 ``(行首字符偏移, 标题层级 1..6)``，跳过 fenced code 块内行。

    仅识别行首（允许前导空白 ≤3）的 ATX ``#``…``######`` 后接空白或行尾。
    """
    out: list[tuple[int, int]] = []
    in_fence = False
    pos = 0
    for line in text.splitlines(keepends=True):
        line_start = pos
        raw = line.rstrip("\n\r")
        stripped_fence = raw.strip()
        if stripped_fence.startswith("```"):
            in_fence = not in_fence
            pos += len(line)
            continue
        if not in_fence:
            m = _ATX.match(raw)
            if m:
                out.append((line_start, len(m.group(1))))
        pos += len(line)
    return out


def _count_by_level_in_range(
    headings: list[tuple[int, int]],
    lo: int,
    hi: int,
    *,
    level_gt: int,
) -> dict[int, int]:
    c: dict[int, int] = {}
    for p, lv in headings:
        if lo <= p < hi and lv > level_gt:
            c[lv] = c.get(lv, 0) + 1
    return c


def _next_boundary_after(
    headings: list[tuple[int, int]],
    p: int,
    L_split: int,
    hi: int,
) -> int:
    """从 ``p`` 之后找第一个 ``level <= L_split`` 的标题行首（不含 ``p`` 自身），若无则 ``hi``。"""
    for q, lv in headings:
        if q <= p:
            continue
        if q >= hi:
            break
        if lv <= L_split:
            return q
    return hi


def _split_slice_at_level(
    headings: list[tuple[int, int]],
    sec_lo: int,
    sec_hi: int,
    L_split: int,
    parent_l_open: int,
) -> list[tuple[int, int, int]]:
    """在 ``[sec_lo, sec_hi)`` 内按 ``L_split`` 切分。

    返回 ``(start, end, l_open)``：以 ``L_split`` 标题开头的块 ``l_open=L_split``；
    首部序言 ``[sec_lo, 第一处 L_split)`` 的 ``l_open=parent_l_open``（递归时沿用父级）。
    """
    starts = [p for p, lv in headings if sec_lo <= p < sec_hi and lv == L_split]
    if not starts:
        return [(sec_lo, sec_hi, parent_l_open)]
    out: list[tuple[int, int, int]] = []
    if sec_lo < starts[0]:
        out.append((sec_lo, starts[0], parent_l_open))
    for p in starts:
        end = _next_boundary_after(headings, p, L_split, sec_hi)
        out.append((p, end, L_split))
    return out


def _pick_split_level(counts: dict[int, int], *, deepest: bool) -> int | None:
    """从 ``{level: count}`` 中取 ``count>=2`` 的最深或最浅层级。"""
    s = {L for L, n in counts.items() if n >= 2}
    if not s:
        return None
    return max(s) if deepest else min(s)


def _subdivide_section(
    text: str,
    headings: list[tuple[int, int]],
    sec_lo: int,
    sec_hi: int,
    l_open: int,
    *,
    deepest: bool,
    single_immediate_strict: bool,
) -> list[tuple[int, int]]:
    """对 ``[sec_lo, sec_hi)`` 递归标题细分，返回叶子 ``(start, end)`` 列表（半开区间）。"""
    if sec_hi <= sec_lo:
        return []

    counts = _count_by_level_in_range(headings, sec_lo, sec_hi, level_gt=l_open)
    if single_immediate_strict and l_open < 6:
        d = l_open + 1
        if counts.get(d, 0) == 1:
            return [(sec_lo, sec_hi)]

    L_split = _pick_split_level(counts, deepest=deepest)
    if L_split is None:
        return [(sec_lo, sec_hi)]

    pieces = _split_slice_at_level(headings, sec_lo, sec_hi, L_split, parent_l_open=l_open)
    leaves = []
    for a, b, l_child in pieces:
        if b <= a:
            continue
        leaves.extend(
            _subdivide_section(
                text,
                headings,
                a,
                b,
                l_open=l_child,
                deepest=deepest,
                single_immediate_strict=single_immediate_strict,
            )
        )
    return leaves


def leaf_ranges_heading_presplit(
    text: str,
    *,
    strategy: Literal[
        "deepest_with_multiple",
        "shallowest_with_multiple",
        "none",
    ] = "deepest_with_multiple",
    fixed_first_level: int | None = None,
    single_immediate_child: Literal["strict", "relaxed"] = "strict",
) -> list[tuple[int, int]]:
    """返回全文上标题递归预切分后的叶子 ``(char_start, char_end)`` 半开区间。"""
    n = len(text)
    if n == 0:
        return []
    headings = parse_atx_heading_spans(text)
    deepest = strategy != "shallowest_with_multiple"
    strict_single = single_immediate_child == "strict"

    if strategy == "none":
        return [(0, n)]

    if fixed_first_level is not None:
        L1 = max(1, min(6, fixed_first_level))
        first_slices = _split_slice_at_level(headings, 0, n, L1, parent_l_open=0)
        leaves = []
        for a, b, l_child in first_slices:
            if b <= a:
                continue
            leaves.extend(
                _subdivide_section(
                    text,
                    headings,
                    a,
                    b,
                    l_open=l_child,
                    deepest=deepest,
                    single_immediate_strict=strict_single,
                )
            )
        return leaves

    global_counts: dict[int, int] = {}
    for _, lv in headings:
        global_counts[lv] = global_counts.get(lv, 0) + 1
    L1 = _pick_split_level(global_counts, deepest=deepest)
    if L1 is None:
        return [(0, n)]

    first_slices = _split_slice_at_level(headings, 0, n, L1, parent_l_open=0)
    leaves = []
    for a, b, l_child in first_slices:
        if b <= a:
            continue
        leaves.extend(
            _subdivide_section(
                text,
                headings,
                a,
                b,
                l_open=l_child,
                deepest=deepest,
                single_immediate_strict=strict_single,
            )
        )
    return leaves


def default_heading_presplit_separator() -> str:
    """与方案 D 导出同形分隔条，标注 v1.1.10 便于区分文件来源。"""
    bar = "#" * 88
    return (
        "\n\n"
        + bar
        + "\n"
        + "##>>> CHUNK_BOUNDARY (heading_presplit v1.1.10 + document_segmentation D) <<<##\n"
        + bar
        + "\n\n"
    )


def iter_heading_presplit_document_segmentation_chunks_for_text(
    full_text: str,
    *,
    source_file: str,
    source_path: str | None,
    pipeline: Any,
    leaf_ranges: list[tuple[int, int]],
    min_chars: int,
    max_chars: int,
    split_overlap: int,
    section_max_chars: int,
) -> Iterator[TextChunk]:
    """先按 ``leaf_ranges`` 叶子切分；仅当叶子长度 ``> section_max_chars`` 时对该子串跑方案 D。

    否则叶子整块作为一个 ``TextChunk``（``extra`` 区分是否经过 D）。
    """
    sid = source_path or source_file
    out_idx = 0
    for s, e in leaf_ranges:
        if e <= s:
            continue
        piece = full_text[s:e]
        if len(piece) <= section_max_chars:
            yield TextChunk(
                text=piece,
                source_file=source_file,
                chunk_index=out_idx,
                char_start=s,
                char_end=e,
                source_path=source_path,
                source_id=sid,
                extra={"chunking": "heading_presplit_leaf", "scheme_d": False},
            )
            out_idx += 1
            continue
        for c in iter_document_segmentation_chunks_for_text(
            piece,
            source_file=source_file,
            source_path=source_path,
            raw_ranges_fn=lambda t, _pipe=pipeline: infer_raw_ranges_from_pipeline(t, _pipe),
            min_chars=min_chars,
            max_chars=max_chars,
            split_overlap=split_overlap,
        ):
            yield TextChunk(
                text=c.text,
                source_file=source_file,
                chunk_index=out_idx,
                char_start=s + c.char_start,
                char_end=s + c.char_end,
                source_path=source_path,
                source_id=sid,
                extra={"chunking": "heading_presplit_d10", "scheme_d": True},
            )
            out_idx += 1


def export_heading_presplit_document_segmentation_dir(
    md_paths: list[Path],
    out_dir: Path,
    pipeline: Any,
    *,
    strategy: str,
    fixed_first_level: int | None,
    single_immediate_child: str,
    min_chars: int,
    max_chars: int,
    split_overlap: int,
    section_max_chars: int,
    chunk_separator: str | None = None,
    progress: bool = True,
) -> list[Path]:
    """将若干 .md 按 v1.1.10 标题预切分 + 段内方案 D 写入 ``out_dir``。"""
    strat: Literal["deepest_with_multiple", "shallowest_with_multiple", "none"]
    if strategy in ("deepest_with_multiple", "shallowest_with_multiple", "none"):
        strat = strategy  # type: ignore[assignment]
    else:
        strat = "deepest_with_multiple"
    single: Literal["strict", "relaxed"] = (
        "relaxed" if single_immediate_child == "relaxed" else "strict"
    )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sep = chunk_separator if chunk_separator is not None else default_heading_presplit_separator()
    written: list[Path] = []
    root = project_root()
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None  # type: ignore[misc, assignment]
    use_bar = bool(progress and tqdm is not None)
    path_iter = tqdm(md_paths, desc="d05 heading+D", unit="file") if use_bar else md_paths

    for md in path_iter:
        p = Path(md)
        if use_bar and hasattr(path_iter, "set_postfix_str"):
            path_iter.set_postfix_str(p.name[:48] + ("…" if len(p.name) > 48 else ""))
        text = p.read_text(encoding="utf-8")
        try:
            sp = p.resolve().relative_to(root).as_posix()
        except ValueError:
            sp = p.name
        leaves = leaf_ranges_heading_presplit(
            text,
            strategy=strat,
            fixed_first_level=fixed_first_level,
            single_immediate_child=single,
        )
        chunks = list(
            iter_heading_presplit_document_segmentation_chunks_for_text(
                text,
                source_file=p.name,
                source_path=sp,
                pipeline=pipeline,
                leaf_ranges=leaves,
                min_chars=min_chars,
                max_chars=max_chars,
                split_overlap=split_overlap,
                section_max_chars=section_max_chars,
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


def split_heading_presplit_export_to_chunks(export_text: str, *, separator: str | None = None) -> list[str]:
    sep = separator if separator is not None else default_heading_presplit_separator()
    return export_text.split(sep)
