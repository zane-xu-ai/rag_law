"""`qa.hit_resolve`：本地源文件重算块。"""

from __future__ import annotations

import pytest

from conf.settings import get_settings
from qa.hit_resolve import resolve_hit_source_text_from_settings


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
