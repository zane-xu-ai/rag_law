"""`qa.streaming.stream_qa_events`：mock 依赖，无 ES / 无真实 LLM。"""

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


class _FakeDelta:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.delta = _FakeDelta(content)


class _FakeChunk:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


def _fake_stream() -> Any:
    yield _FakeChunk("答")
    yield _FakeChunk("案")


def test_stream_qa_events_emits_phases_done_and_ttft(monkeypatch: pytest.MonkeyPatch) -> None:
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
                        "text": "条文示例",
                    },
                }
            ]

    class FakeCompletions:
        @staticmethod
        def create(**kw: Any) -> Any:
            assert kw.get("stream") is True
            return _fake_stream()

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

    from qa.streaming import stream_qa_events

    events = list(
        stream_qa_events(
            "测试问题？",
            settings=settings,
            conversation_id="cid-1",
        )
    )

    types = [e["type"] for e in events]
    assert "start" in types
    assert "retrieval" in types
    assert "delta" in types
    done = [e for e in events if e["type"] == "done"][0]
    assert done["ok"] is True
    assert done["conversation_id"] == "cid-1"
    assert done["text"] == "答案"
    assert done["ttft_ms"] is not None
    assert done["total_ms"] is not None
    assert done["total_ms"] >= done["ttft_ms"]
    assert "settings_resolve" in done["timings"]
    assert "embed_query" in done["timings"]
    assert "llm_stream_open" in done["timings"]
