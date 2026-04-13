"""`qa.hit_resolve`：本地源文件重算块。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chunking.split import TextChunk
from conf.settings import get_settings
from qa.hit_resolve import (
    _pick_chunk_for_hit,
    _read_utf8_under_root,
    apply_hit_resolve_to_hits,
    resolve_hit_source_text_from_settings,
)


def _base_env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    base: dict[str, str] = {
        "MODEL_API_KEY": "k",
        "MODEL_BASE_URL": "https://example.com/v1",
        "MODEL_NAME": "q",
        "ES_HOST": "localhost",
        "ES_PORT": "9200",
        "ES_INDEX": "t",
        "BGE_M3_PATH": "/opt/bge",
        "CHUNK_SIZE": "20",
        "CHUNK_OVERLAP": "4",
    }
    base.update(extra)
    for k, v in base.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_resolve_disabled_returns_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _base_env(monkeypatch, QA_RESOLVE_CHUNKS_FROM_SOURCE="false")
    get_settings.cache_clear()
    s = get_settings()
    src = {"text": "old", "source_path": "x.md", "chunk_index": 0}
    out = resolve_hit_source_text_from_settings(src, settings=s, embedding_backend=None, root=tmp_path)
    assert out["text"] == "old"


def test_resolve_replaces_text_when_file_exists(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _base_env(
        monkeypatch,
        QA_RESOLVE_CHUNKS_FROM_SOURCE="true",
        CHUNK_BOUNDARY_AWARE="false",
        CHUNK_SEMANTIC_MERGE_ENABLED="false",
    )
    get_settings.cache_clear()
    s = get_settings()

    (tmp_path / "sub").mkdir()
    body = "a" * 25
    rel = "sub/doc.md"
    (tmp_path / rel).write_text(body, encoding="utf-8")

    src = {
        "text": "stale from es",
        "source_file": "doc.md",
        "source_path": rel,
        "chunk_index": 0,
        "char_start": 0,
        "char_end": 20,
    }
    out = resolve_hit_source_text_from_settings(src, settings=s, embedding_backend=None, root=tmp_path)
    assert out["text"] == body[0:20]
    assert out["chunk_index"] == 0


def test_read_utf8_empty_or_absolute(tmp_path: Path) -> None:
    assert _read_utf8_under_root(tmp_path, "") is None
    assert _read_utf8_under_root(tmp_path, "   ") is None
    assert _read_utf8_under_root(tmp_path, "/abs/outside.md") is None


def test_read_utf8_path_escape(tmp_path: Path) -> None:
    (tmp_path / "safe.md").write_text("ok", encoding="utf-8")
    assert _read_utf8_under_root(tmp_path, "../safe.md") is None


def test_pick_chunk_for_hit_empty() -> None:
    assert _pick_chunk_for_hit([], char_start=0, char_end=10, chunk_index=0) is None


def test_pick_chunk_for_hit_overlap_and_tie_break() -> None:
    c0 = TextChunk(text="aa", source_file="f.md", chunk_index=0, char_start=0, char_end=2)
    c1 = TextChunk(text="bb", source_file="f.md", chunk_index=1, char_start=2, char_end=4)
    assert _pick_chunk_for_hit([c0, c1], char_start=1, char_end=3, chunk_index=9) is c0
    c2 = TextChunk(text="cc", source_file="f.md", chunk_index=2, char_start=0, char_end=4)
    assert _pick_chunk_for_hit([c1, c2], char_start=0, char_end=4, chunk_index=9) is c2


def test_pick_chunk_for_hit_bad_char_range_falls_back() -> None:
    c0 = TextChunk(text="a", source_file="f.md", chunk_index=0, char_start=0, char_end=1)
    c1 = TextChunk(text="b", source_file="f.md", chunk_index=1, char_start=1, char_end=2)
    assert (
        _pick_chunk_for_hit([c0, c1], char_start="x", char_end="y", chunk_index=None) is c0
    )
    assert _pick_chunk_for_hit([c0, c1], char_start=0, char_end=0, chunk_index=99) is c0
    assert _pick_chunk_for_hit([c0, c1], char_start=0, char_end=0, chunk_index=1) is c1
    assert _pick_chunk_for_hit([c0, c1], char_start=None, char_end=5, chunk_index="bad") is c0


def test_pick_chunk_for_hit_tie_prefers_smaller_chunk_index() -> None:
    c_hi = TextChunk(text="a", source_file="f.md", chunk_index=5, char_start=0, char_end=4)
    c_lo = TextChunk(text="b", source_file="f.md", chunk_index=3, char_start=2, char_end=6)
    assert _pick_chunk_for_hit([c_hi, c_lo], char_start=1, char_end=5, chunk_index=0) is c_lo


def test_resolve_empty_source_no_chunks_returns_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _base_env(
        monkeypatch,
        QA_RESOLVE_CHUNKS_FROM_SOURCE="true",
        CHUNK_BOUNDARY_AWARE="false",
        CHUNK_SEMANTIC_MERGE_ENABLED="false",
    )
    get_settings.cache_clear()
    s = get_settings()
    (tmp_path / "empty.md").write_text("", encoding="utf-8")
    src = {"text": "only", "source_path": "empty.md", "chunk_index": 0}
    out = resolve_hit_source_text_from_settings(src, settings=s, embedding_backend=None, root=tmp_path)
    assert out == src


@patch("qa.hit_resolve.iter_chunks_in_memory_like_ingest")
def test_resolve_passes_embedding_backend_when_semantic_merge_embedding(
    mock_iter: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _base_env(
        monkeypatch,
        QA_RESOLVE_CHUNKS_FROM_SOURCE="true",
        CHUNK_BOUNDARY_AWARE="false",
        CHUNK_SEMANTIC_MERGE_ENABLED="true",
        CHUNK_SEMANTIC_MERGE_SIMILARITY="embedding",
    )
    get_settings.cache_clear()
    s = get_settings()
    (tmp_path / "one.md").write_text("a" * 40, encoding="utf-8")
    c0 = TextChunk(text="a" * 20, source_file="one.md", chunk_index=0, char_start=0, char_end=20)
    mock_iter.return_value = iter([c0])
    emb = MagicMock()
    emb.embed_query = MagicMock(return_value=[0.0])
    emb.embed_documents = MagicMock(return_value=[[0.0]])
    src = {
        "text": "stale",
        "source_file": "one.md",
        "source_path": "one.md",
        "chunk_index": 0,
        "char_start": 0,
        "char_end": 20,
    }
    out = resolve_hit_source_text_from_settings(src, settings=s, embedding_backend=emb, root=tmp_path)
    assert out["text"] == c0.text
    call_kw = mock_iter.call_args.kwargs
    assert call_kw["embedding_backend"] is emb


def test_resolve_missing_file_returns_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, QA_RESOLVE_CHUNKS_FROM_SOURCE="true")
    get_settings.cache_clear()
    s = get_settings()
    src = {"text": "only", "source_path": "nope.md", "chunk_index": 0}
    out = resolve_hit_source_text_from_settings(src, settings=s, embedding_backend=None, root=tmp_path)
    assert out == src


def test_apply_hit_resolve_empty_and_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _base_env(monkeypatch, QA_RESOLVE_CHUNKS_FROM_SOURCE="false")
    get_settings.cache_clear()
    s = get_settings()
    hits = [{"source": {"text": "x"}}]
    assert apply_hit_resolve_to_hits([], settings=s, embedding_backend=None, root=tmp_path) == []
    assert apply_hit_resolve_to_hits(hits, settings=s, embedding_backend=None, root=tmp_path) == hits


def test_apply_hit_resolve_rewrites_hit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base_env(
        monkeypatch,
        QA_RESOLVE_CHUNKS_FROM_SOURCE="true",
        CHUNK_BOUNDARY_AWARE="false",
        CHUNK_SEMANTIC_MERGE_ENABLED="false",
    )
    get_settings.cache_clear()
    s = get_settings()
    (tmp_path / "r.md").write_text("z" * 30, encoding="utf-8")
    hits = [
        {
            "id": "1",
            "source": {
                "text": "old",
                "source_file": "r.md",
                "source_path": "r.md",
                "chunk_index": 0,
                "char_start": 0,
                "char_end": 20,
            },
        }
    ]
    out = apply_hit_resolve_to_hits(hits, settings=s, embedding_backend=None, root=tmp_path)
    assert out[0]["id"] == "1"
    assert out[0]["source"]["text"] == ("z" * 20)
