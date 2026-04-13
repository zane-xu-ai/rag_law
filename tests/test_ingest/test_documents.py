"""ingest.documents 纯函数。"""

from __future__ import annotations

from chunking.split import TextChunk
from ingest.documents import chunk_embedding_to_source, sha256_utf8_file


def test_chunk_embedding_to_source_shape() -> None:
    c = TextChunk(
        text="hello",
        source_file="a.md",
        chunk_index=0,
        char_start=0,
        char_end=5,
        source_path="data/a.md",
        source_id="data/a.md",
    )
    emb = [0.1, 0.2, 0.3]
    d = chunk_embedding_to_source(c, emb, source_sha256="abc" * 10 + "ab")
    assert d["text"] == "hello"
    assert d["embedding"] == emb
    assert d["source_file"] == "a.md"
    assert d["chunk_type"] == "text"
    assert d["mime_type"] == "text/markdown"
    assert d["source_doc_id"] == "data/a.md"
    assert d["source_sha256"] == "abc" * 10 + "ab"
    assert d["source_oss_url"] == ""
    assert d["chunk_version"] == ""


def test_chunk_embedding_to_source_empty_sha_gets_default() -> None:
    c = TextChunk(
        text="x",
        source_file="f.md",
        chunk_index=0,
        char_start=0,
        char_end=1,
    )
    d = chunk_embedding_to_source(c, [1.0])
    assert d["source_sha256"] == ""
    assert d["source_oss_url"] == ""
    assert d["chunk_version"] == ""


def test_chunk_embedding_to_source_oss_url() -> None:
    c = TextChunk(
        text="x",
        source_file="f.md",
        chunk_index=0,
        char_start=0,
        char_end=1,
        source_path="data/md_minerU/f.md",
    )
    d = chunk_embedding_to_source(
        c,
        [1.0],
        source_oss_url="https://md3.oss-cn-beijing.aliyuncs.com/a/b.md",
    )
    assert d["source_oss_url"] == "https://md3.oss-cn-beijing.aliyuncs.com/a/b.md"


def test_chunk_embedding_promotes_heading_fields_from_extra() -> None:
    c = TextChunk(
        text="x",
        source_file="f.md",
        chunk_index=0,
        char_start=0,
        char_end=1,
        source_path="data/f.md",
        extra={
            "chunking": "heading_presplit_leaf",
            "document_chunk_id": 0,
            "section_heading_id": "data/f.md#h1@0",
            "heading_level": 1,
            "leaf_char_start": 0,
            "leaf_char_end": 10,
        },
    )
    d = chunk_embedding_to_source(c, [0.1])
    assert d["document_chunk_id"] == 0
    assert d["section_heading_id"] == "data/f.md#h1@0"
    assert d["heading_level"] == 1
    assert d["extra"]["chunking"] == "heading_presplit_leaf"
    assert d["extra"]["leaf_char_start"] == 0
    assert "document_chunk_id" not in d["extra"]


def test_chunk_embedding_to_source_chunk_version() -> None:
    c = TextChunk(
        text="v",
        source_file="v.md",
        chunk_index=0,
        char_start=0,
        char_end=1,
    )
    d = chunk_embedding_to_source(c, [0.1], chunk_version="1.1.7")
    assert d["chunk_version"] == "1.1.7"


def test_sha256_utf8_file(tmp_path) -> None:
    p = tmp_path / "t.md"
    p.write_bytes("你好\n".encode("utf-8"))
    h = sha256_utf8_file(p)
    assert len(h) == 64
