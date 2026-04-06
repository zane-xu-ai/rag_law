"""`qa.pipeline.answer_question`：mock 依赖，无 ES / 无 openai 网络。"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from conf.settings import get_settings


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "MODEL_API_KEY": "test-model-api-key",
        "MODEL_BASE_URL": "https://dashscope.example.com/compatible-mode/v1",
        "MODEL_NAME": "qwen-test",
        "ES_HOST": "localhost",
        "ES_PORT": "9200",
        "ES_INDEX": "test_index",
        "BGE_M3_PATH": "/opt/models/bge-m3",
        "CHUNK_SIZE": "800",
        "CHUNK_OVERLAP": "50",
        "RETRIEVAL_K": "3",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PARENT_CHUNK_SIZE", raising=False)
    monkeypatch.delenv("ES_USER", raising=False)
    monkeypatch.delenv("ES_PASSWORD", raising=False)


def test_answer_question_returns_message_content(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    get_settings.cache_clear()
    settings = get_settings()

    class FakeEmbedder:
        dense_dimension = 4

        def embed_query(self, q: str) -> list[float]:
            return [0.25, 0.25, 0.25, 0.25]

    class FakeStore:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def search_knn(self, qv: list[float], k: int) -> list[dict[str, Any]]:
            return [
                {
                    "id": "f:0",
                    "score": 0.99,
                    "source": {
                        "source_file": "data/试.md",
                        "chunk_index": 0,
                        "text": "示例",
                    },
                }
            ]

    class FakeMsg:
        content = "答复正文"

    class FakeChoice:
        message = FakeMsg()

    class FakeResp:
        choices = [FakeChoice()]

    class FakeCompletions:
        @staticmethod
        def create(**kw: Any) -> FakeResp:
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kw: Any) -> None:
            pass

        chat = FakeChat()

    fake_openai_mod = ModuleType("openai")
    fake_openai_mod.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)

    monkeypatch.setattr("embeddings.build_embedder", lambda s: FakeEmbedder())
    monkeypatch.setattr("es_store.client.elasticsearch_client", lambda s: object())
    monkeypatch.setattr("es_store.store.EsChunkStore", FakeStore)

    from qa.pipeline import answer_question

    out = answer_question(settings, "问什么？")
    assert out == "答复正文"


def test_answer_question_empty_choice_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    get_settings.cache_clear()
    settings = get_settings()

    class FakeEmbedder:
        dense_dimension = 4

        def embed_query(self, q: str) -> list[float]:
            return [1.0, 0.0, 0.0, 0.0]

    class FakeStore:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def search_knn(self, qv: list[float], k: int) -> list[dict[str, Any]]:
            return []

    class FakeResp:
        choices: list = []

    class FakeCompletions:
        @staticmethod
        def create(**kw: Any) -> FakeResp:
            return FakeResp()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kw: Any) -> None:
            pass

        chat = FakeChat()

    fake_openai_mod = ModuleType("openai")
    fake_openai_mod.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)

    monkeypatch.setattr("embeddings.build_embedder", lambda s: FakeEmbedder())
    monkeypatch.setattr("es_store.client.elasticsearch_client", lambda s: object())
    monkeypatch.setattr("es_store.store.EsChunkStore", FakeStore)

    from qa.pipeline import answer_question

    assert answer_question(settings, "x") == ""
