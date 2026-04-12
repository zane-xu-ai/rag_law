"""chunking.document_segmentation：方案 D 切块与导出（不加载真实 ModelScope，避免 CI 依赖 GPU/大模型）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from chunking.document_segmentation import (
    _split_range_max_len_document_d,
    default_document_segmentation_separator,
    export_document_segmentation_chunks_dir,
    infer_raw_ranges_from_pipeline,
    iter_document_segmentation_chunks_for_text,
    segments_to_char_ranges,
    split_document_segmentation_export_to_chunks,
)


def test_segments_to_char_ranges_exact_join() -> None:
    text = "abcdef"
    assert segments_to_char_ranges(text, ["abc", "def"]) == [(0, 3), (3, 6)]


def test_segments_to_char_ranges_find() -> None:
    text = "aaaxbbb"
    assert segments_to_char_ranges(text, ["aaa", "bbb"]) == [(0, 4), (4, 7)]


def test_segments_to_char_ranges_loose_tabs_partition_full_text() -> None:
    """模型片段带制表符、与 MinerU 源文不一致时，用「下一段起点」划分仍应无间隙覆盖全文。"""
    full = "# 中华人民共和国刑法\n第一章 总则\n"
    segments = [
        "\t# 中华人民共和国刑法\n",
        "第一章 总则\n",
    ]
    ranges = segments_to_char_ranges(full, segments)
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(full)
    assert "".join(full[a:b] for a, b in ranges) == full


def test_split_range_document_d_prefers_newline() -> None:
    """超长再切分应优先落在换行上，避免纯字符窗切断行中段。"""
    body = ("a" * 130) + "\n" + ("b" * 200)
    ranges = _split_range_max_len_document_d(body, 0, len(body), max_chars=140, overlap=0)
    assert "".join(body[a:b] for a, b in ranges) == body
    assert ranges[0] == (0, 131)
    assert body[ranges[0][1] - 1] == "\n"


def test_split_range_document_d_many_short_lines() -> None:
    """多行短行：再切分时除最后一块外均应以换行结尾（与 MinerU 法规 md 版式一致）。"""
    snip = "".join(f"第{i:02d}条 一句。\n" for i in range(1, 45))
    ranges = _split_range_max_len_document_d(snip, 0, len(snip), max_chars=80, overlap=0)
    assert "".join(snip[a:b] for a, b in ranges) == snip
    for a, b in ranges[:-1]:
        assert snip[b - 1] == "\n", (a, b, repr(snip[a:b][-20:]))


def test_default_separator_and_split_roundtrip() -> None:
    sep = default_document_segmentation_separator()
    assert "document_segmentation D" in sep
    parts = ["x", "y"]
    export = parts[0] + sep + parts[1]
    assert split_document_segmentation_export_to_chunks(export) == parts


def test_infer_raw_ranges_from_fake_pipeline() -> None:
    class FakeP:
        def __call__(self, x: str) -> list[str]:
            assert x == "abcdefghij"
            return ["abcde", "fghij"]

    assert infer_raw_ranges_from_pipeline("abcdefghij", FakeP()) == [(0, 5), (5, 10)]


def test_iter_document_segmentation_chunks_merge_split() -> None:
    text = "a" * 5000

    def raw_fn(_t: str) -> list[tuple[int, int]]:
        return [(0, 5000)]

    chunks = list(
        iter_document_segmentation_chunks_for_text(
            text,
            source_file="f.md",
            source_path="f.md",
            raw_ranges_fn=raw_fn,
            min_chars=200,
            max_chars=2200,
            split_overlap=0,
        )
    )
    assert len(chunks) >= 3
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == 5000
    assert all(c.extra and c.extra.get("chunking") == "document_segmentation_d" for c in chunks)


def test_export_document_segmentation_dir(tmp_path: Path) -> None:
    class FakeP:
        def __call__(self, x: str) -> list[str]:
            if len(x) <= 3:
                return [x]
            return [x[:3], x[3:]]

    md = tmp_path / "t.md"
    md.write_text("abcdef", encoding="utf-8")
    out = tmp_path / "out"
    written = export_document_segmentation_chunks_dir(
        [md],
        out,
        FakeP(),
        min_chars=1,
        max_chars=100,
        split_overlap=0,
        progress=False,
    )
    assert len(written) == 1
    body = written[0].read_text(encoding="utf-8")
    sep = default_document_segmentation_separator()
    assert sep in body
    assert split_document_segmentation_export_to_chunks(body) == ["abc", "def"]


def test_build_pipeline_raises_without_modelscope() -> None:
    from chunking.document_segmentation import build_document_segmentation_pipeline

    try:
        import modelscope  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError, match="modelscope"):
            build_document_segmentation_pipeline("/nonexistent/model")
    else:
        pytest.skip("modelscope 已安装，跳过 ImportError 断言")
