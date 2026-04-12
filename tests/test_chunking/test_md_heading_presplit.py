"""chunking.md_heading_presplit：ATX 标题递归预切分。"""

from __future__ import annotations

from chunking.md_heading_presplit import leaf_ranges_heading_presplit, parse_atx_heading_spans


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
