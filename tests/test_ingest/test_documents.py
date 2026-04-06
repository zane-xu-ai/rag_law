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


def test_sha256_utf8_file(tmp_path) -> None:
    p = tmp_path / "t.md"
    p.write_bytes("你好\n".encode("utf-8"))
    h = sha256_utf8_file(p)
    assert len(h) == 64
