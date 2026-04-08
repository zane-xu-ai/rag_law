"""对应 `src/chunking/split.py`：滑窗与目录遍历。"""

from __future__ import annotations

from pathlib import Path

import pytest

from chunking.split import (
    TextChunk,
    iter_chunks_for_data_dir,
    iter_chunks_for_text,
    iter_file_chunks,
    iter_text_slices,
    load_all_chunks,
    semantic_merge_chunks,
)


def test_iter_text_slices_basic() -> None:
    chunks = list(iter_text_slices("abcdefghij", chunk_size=4, chunk_overlap=1))
    texts = [t for t, _, _ in chunks]
    # 步长 3：末窗 [6:10] 已覆盖全文，不再单独产出仅含末字符的块
    assert texts == ["abcd", "defg", "ghij"]
    assert chunks[0][1:] == (0, 4)
    assert chunks[-1][0] == "ghij"
    assert chunks[-1][1:] == (6, 10)


def test_iter_text_slices_overlap_zero() -> None:
    chunks = list(iter_text_slices("abcdefgh", chunk_size=4, chunk_overlap=0))
    assert [t for t, _, _ in chunks] == ["abcd", "efgh"]


def test_iter_text_slices_single_chunk_when_text_shorter_than_size() -> None:
    chunks = list(iter_text_slices("abc", chunk_size=10, chunk_overlap=0))
    assert len(chunks) == 1
    assert chunks[0][0] == "abc"
    assert chunks[0][1:] == (0, 3)


def test_iter_text_slices_empty_yields_nothing() -> None:
    assert list(iter_text_slices("", chunk_size=100, chunk_overlap=0)) == []


def test_iter_text_slices_overlap_must_be_less_than_size() -> None:
    with pytest.raises(ValueError, match="chunk_overlap"):
        list(iter_text_slices("abc", chunk_size=3, chunk_overlap=3))


def test_iter_chunks_for_text_metadata() -> None:
    chunks = list(
        iter_chunks_for_text(
            "0123456789",
            source_file="t.md",
            source_path="data/t.md",
            chunk_size=4,
            chunk_overlap=1,
        )
    )
    assert all(isinstance(c, TextChunk) for c in chunks)
    assert chunks[0].source_file == "t.md"
    assert chunks[0].source_path == "data/t.md"
    assert chunks[0].source_id == "data/t.md"
    assert chunks[0].mime_type == "text/markdown"
    assert chunks[0].doc_type == "law_md"
    assert chunks[0].domain == "law"
    assert chunks[0].chunk_index == 0


def test_iter_chunks_for_data_dir_two_files(tmp_path: Path) -> None:
    d = tmp_path / "data_md"
    d.mkdir()
    (d / "a.md").write_text("0000000000", encoding="utf-8")
    (d / "b.md").write_text("11111", encoding="utf-8")
    chunks = list(
        iter_chunks_for_data_dir(
            d,
            chunk_size=4,
            chunk_overlap=0,
            root=tmp_path,
        )
    )
    a_chunks = [c for c in chunks if c.source_file == "a.md"]
    b_chunks = [c for c in chunks if c.source_file == "b.md"]
    # a.md 10 字符、size=4、overlap=0 → 4+4+2 共 3 块；b.md 5 字符 → 4+1 共 2 块
    assert [c.chunk_index for c in a_chunks] == [0, 1, 2]
    assert [c.chunk_index for c in b_chunks] == [0, 1]
    assert a_chunks[0].char_start == 0


def test_load_all_chunks_same_as_list_iter(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "x.md").write_text("abc", encoding="utf-8")
    a = load_all_chunks(d, chunk_size=2, chunk_overlap=0, root=tmp_path)
    b = list(iter_chunks_for_data_dir(d, chunk_size=2, chunk_overlap=0, root=tmp_path))
    assert a == b


def test_iter_file_chunks_via_path(tmp_path: Path) -> None:
    p = tmp_path / "single.md"
    p.write_text("hello", encoding="utf-8")
    chunks = list(iter_file_chunks(p, chunk_size=3, chunk_overlap=1, root=tmp_path))
    assert len(chunks) >= 1
    assert chunks[0].text == "hel"


def test_semantic_merge_chunks_merge_high_similarity() -> None:
    chunks = [
        TextChunk("合同纠纷的诉讼时效为三年。", "a.md", 0, 0, 14),
        TextChunk("合同纠纷的诉讼时效通常是三年。", "a.md", 1, 14, 30),
    ]
    merged, stats = semantic_merge_chunks(
        chunks,
        similarity_threshold=0.5,
        min_chunk_chars=80,
        max_chunk_chars=200,
    )
    assert len(merged) == 1
    assert merged[0].chunk_index == 0
    assert merged[0].char_start == 0
    assert merged[0].char_end == 30
    assert stats["merge_hits"] >= 1


def test_semantic_merge_chunks_keep_low_similarity() -> None:
    chunks = [
        TextChunk("合同纠纷的诉讼时效为三年。", "a.md", 0, 0, 14),
        TextChunk("刑法关于盗窃罪的量刑标准。", "a.md", 1, 14, 28),
    ]
    merged, stats = semantic_merge_chunks(
        chunks,
        similarity_threshold=0.95,
        min_chunk_chars=80,
        max_chunk_chars=200,
    )
    assert len(merged) == 2
    assert merged[0].chunk_index == 0
    assert merged[1].chunk_index == 1
    assert stats["merge_hits"] == 0


def test_iter_chunks_for_text_semantic_merge_enabled() -> None:
    text = "合同纠纷的诉讼时效为三年。合同纠纷的诉讼时效通常是三年。"
    chunks = list(
        iter_chunks_for_text(
            text,
            source_file="a.md",
            source_path="data/a.md",
            chunk_size=16,
            chunk_overlap=0,
            semantic_merge_enabled=True,
            semantic_merge_threshold=0.0,
            semantic_merge_min_chars=80,
            semantic_merge_max_chars=200,
        )
    )
    assert len(chunks) == 1
