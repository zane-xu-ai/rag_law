"""chunking.breakpoint_embed：嵌入断点切分（方案 C）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from chunking.breakpoint_embed import (
    adjacent_cosine_percentiles,
    breakpoint_embed_diagnostics,
    breakpoint_pipeline_stages,
    compute_adjacent_window_cosines,
    default_chunk_separator,
    export_breakpoint_chunks_dir,
    iter_breakpoint_chunks_for_text,
    raw_breakpoint_ranges,
    split_breakpoint_export_to_chunks,
)


class _FakeEmb:
    dense_dimension = 4

    def __init__(self, *, same: bool = True) -> None:
        self._same = same

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._same:
            v = [0.5, 0.5, 0.5, 0.5]
            return [list(v) for _ in texts]
        out: list[list[float]] = []
        for t in texts:
            if "MARK" in t:
                out.append([1.0, 0.0, 0.0, 0.0])
            else:
                out.append([0.0, 1.0, 0.0, 0.0])
        return out

    def embed_query(self, text: str) -> list[float]:
        return [0.25, 0.25, 0.25, 0.25]


def test_iter_empty_text() -> None:
    emb = _FakeEmb()
    assert list(iter_breakpoint_chunks_for_text("", source_file="x.md", source_path=None, embedder=emb)) == []


def test_iter_short_single_window() -> None:
    emb = _FakeEmb()
    t = "ab" * 80
    chunks = list(
        iter_breakpoint_chunks_for_text(
            t,
            source_file="f.md",
            source_path="f.md",
            embedder=emb,
            window_chars=256,
            stride_chars=128,
            sim_threshold=0.99,
            min_chars=10,
            max_chars=5000,
        )
    )
    assert len(chunks) == 1
    assert chunks[0].text == t
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == len(t)


def test_default_separator_contains_banner() -> None:
    s = default_chunk_separator()
    assert "CHUNK_BOUNDARY" in s
    assert s.count("#") >= 80


def test_split_breakpoint_export_roundtrip() -> None:
    sep = default_chunk_separator()
    parts = ["aaa", "bbb"]
    export = parts[0] + sep + parts[1]
    assert split_breakpoint_export_to_chunks(export) == parts


def test_pack_pipeline_matches_iter_chunks() -> None:
    emb = _FakeEmb(same=True)
    t = "y" * 800
    pack = compute_adjacent_window_cosines(
        t, emb, window_chars=100, stride_chars=50
    )
    st = breakpoint_pipeline_stages(
        t,
        pack,
        sim_threshold=0.99,
        min_chars=80,
        max_chars=300,
        split_overlap=0,
    )
    chunks = list(
        iter_breakpoint_chunks_for_text(
            t,
            source_file="x.md",
            source_path="x.md",
            embedder=emb,
            window_chars=100,
            stride_chars=50,
            sim_threshold=0.99,
            min_chars=80,
            max_chars=300,
            split_overlap=0,
        )
    )
    fr = st["final_ranges"]
    assert len(fr) == len(chunks)
    for (a, b), c in zip(fr, chunks, strict=True):
        assert (a, b) == (c.char_start, c.char_end)


def test_raw_vs_merged_counts() -> None:
    emb = _FakeEmb(same=False)
    # 两段：前段无 MARK，后段有 MARK → 相邻窗 sim 低 → 断点
    t = ("a" * 300) + ("MARK" + "b" * 300)
    pack = compute_adjacent_window_cosines(t, emb, window_chars=80, stride_chars=40)
    raw = raw_breakpoint_ranges(
        pack["text_len"], pack["starts"], pack["adjacent_cosine"], 0.72
    )
    assert len(raw) >= 1
    pct = adjacent_cosine_percentiles(pack["adjacent_cosine"])
    assert "p25" in pct or "p50" in pct


def test_diagnostics_degenerates_when_all_sims_high() -> None:
    """相邻窗向量相同 → 无低于阈值的边 → 长文仅靠 max_chars 劈分。"""
    emb = _FakeEmb(same=True)
    t = "x" * 5000
    d = breakpoint_embed_diagnostics(
        t,
        emb,
        window_chars=256,
        stride_chars=128,
        sim_threshold=0.72,
        min_chars=200,
        max_chars=2200,
    )
    assert d["edges_below_threshold"] == 0
    assert d["only_max_chars_split"] is True
    assert d["merged_range_count"] == 1
    assert d["max_chars_slices_est"] >= 2


def test_export_writes_file(tmp_path: Path) -> None:
    md = tmp_path / "demo.md"
    md.write_text("x" * 400, encoding="utf-8")
    out = tmp_path / "out"
    emb = _FakeEmb()
    written = export_breakpoint_chunks_dir(
        [md],
        out,
        emb,
        window_chars=100,
        stride_chars=50,
        sim_threshold=0.99,
        min_chars=50,
        max_chars=3000,
        progress=False,
    )
    assert len(written) == 1
    body = written[0].read_text(encoding="utf-8")
    assert "x" * 400 in body or body.count("x") >= 400
