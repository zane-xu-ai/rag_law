"""chunking.md_heading_presplit：ATX 标题递归预切分。"""

from __future__ import annotations

from chunking.md_heading_presplit import (
    iter_heading_presplit_document_segmentation_chunks_for_text,
    leaf_ranges_heading_presplit,
    parse_atx_heading_spans,
)


def test_parse_atx_skips_fence() -> None:
    text = "# A\n```\n# fake\n```\n## B\n"
    hs = parse_atx_heading_spans(text)
    levels = [lv for _, lv in hs]
    assert levels == [1, 2]


def test_two_h1_splits_and_recurses_h2() -> None:
    """全文仅两个 ``#``、两个 ``##`` 全在第二章时，``deepest`` 会先按 ``##`` 切；用 ``shallowest`` 先按章再按节。"""
    md = (
        "# 第一章\n\n"
        "intro\n\n"
        "# 第二章\n\n"
        "## 第一节\n\n"
        "a\n\n"
        "## 第二节\n\n"
        "b\n\n"
    )
    leaves = leaf_ranges_heading_presplit(
        md, strategy="shallowest_with_multiple", single_immediate_child="strict"
    )
    joined = "".join(md[s:e] for s, e in leaves)
    assert joined == md
    assert len(leaves) >= 3
    assert any("第一章" in md[s:e] for s, e in leaves)


def test_strict_single_immediate_child_blocks_deeper_split() -> None:
    """首轮 ``shallowest`` 按 ``#`` 分章后：章内仅一条 ``##`` 时 strict 不再按 ``###`` 细分。"""
    md = (
        "# A\n\n## 唯一节\n\n"
        "### x\n\n"
        "### y\n\n"
        "# B\n\n"
        "tail\n"
    )
    leaves_strict = leaf_ranges_heading_presplit(
        md, strategy="shallowest_with_multiple", single_immediate_child="strict"
    )
    leaves_relaxed = leaf_ranges_heading_presplit(
        md, strategy="shallowest_with_multiple", single_immediate_child="relaxed"
    )
    assert len(leaves_strict) < len(leaves_relaxed)


def test_none_strategy_one_leaf() -> None:
    md = "# A\n\n# B\n"
    leaves = leaf_ranges_heading_presplit(md, strategy="none")
    assert leaves == [(0, len(md))]


def test_fixed_first_level() -> None:
    md = "# A\nx\n## b\ny\n# C\nz\n"
    leaves = leaf_ranges_heading_presplit(
        md, strategy="deepest_with_multiple", fixed_first_level=1, single_immediate_child="strict"
    )
    assert len(leaves) >= 2


def test_iter_heading_presplit_extra_section_id_prelude() -> None:
    """无标题全文单叶：``section_heading_id`` 为 ``#prelude@0``。"""
    md = "hello\n"
    leaves = leaf_ranges_heading_presplit(md, strategy="none")

    class _P:
        def __call__(self, x: str) -> list[str]:
            return [x]

    chunks = list(
        iter_heading_presplit_document_segmentation_chunks_for_text(
            md,
            source_file="noh.md",
            source_path="data/noh.md",
            pipeline=_P(),
            leaf_ranges=leaves,
            min_chars=0,
            max_chars=99,
            split_overlap=0,
            section_max_chars=100,
        )
    )
    assert len(chunks) == 1
    assert chunks[0].extra["section_heading_id"] == "data/noh.md#prelude@0"
    assert chunks[0].extra["document_chunk_id"] == 0
    assert chunks[0].chunk_index == 0
    assert "heading_level" not in chunks[0].extra


def test_iter_heading_presplit_extra_section_id_with_atx() -> None:
    md = "# 标题\n\nbody\n"
    leaves = leaf_ranges_heading_presplit(md, strategy="none")

    class _P:
        def __call__(self, x: str) -> list[str]:
            return [x]

    chunks = list(
        iter_heading_presplit_document_segmentation_chunks_for_text(
            md,
            source_file="h.md",
            source_path="law/h.md",
            pipeline=_P(),
            leaf_ranges=leaves,
            min_chars=0,
            max_chars=99,
            split_overlap=0,
            section_max_chars=100,
        )
    )
    assert len(chunks) == 1
    ex = chunks[0].extra
    assert ex["heading_level"] == 1
    assert ex["section_heading_id"] == "law/h.md#h1@0"
    assert ex["document_chunk_id"] == 0


def test_iter_heading_presplit_scheme_d_multiple_chunks_distinct_doc_chunk_id() -> None:
    """叶内方案 D 多块时 ``document_chunk_id`` 递增，``section_heading_id`` 仍同叶。"""
    md = "# H\n\n" + "x" * 20
    leaves = leaf_ranges_heading_presplit(md, strategy="none")

    class _P:
        def __call__(self, x: str) -> list[str]:
            if len(x) >= 10:
                return [x[:8], x[8:]]
            return [x]

    chunks = list(
        iter_heading_presplit_document_segmentation_chunks_for_text(
            md,
            source_file="long.md",
            source_path="p/long.md",
            pipeline=_P(),
            leaf_ranges=leaves,
            min_chars=0,
            max_chars=100,
            split_overlap=0,
            section_max_chars=5,
        )
    )
    assert len(chunks) == 2
    assert chunks[0].extra["document_chunk_id"] == 0
    assert chunks[1].extra["document_chunk_id"] == 1
    assert chunks[0].extra["section_heading_id"] == chunks[1].extra["section_heading_id"]
    assert chunks[0].extra["scheme_d"] is True
    assert chunks[0].extra["chunking"] == "heading_presplit_d10"
