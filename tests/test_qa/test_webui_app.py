"""`qa.webui.app`：健康检查与 SSE（mock `stream_qa_events` / `find_spec`）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _FakeEmbedder:
    dense_dimension = 4

    def embed_query(self, q: str) -> list[float]:
        return [0.25, 0.25, 0.25, 0.25]


class _FakeOpenAI:
    def __init__(self, **kw: object) -> None:
        pass


def _qa_webui_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """与 `test_streaming` 一致，满足 `get_settings()` 必填项。"""
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


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """lifespan 会加载 embedder/ES/OpenAI；用 mock 避免真实 BGE 与网络。"""
    _qa_webui_env(monkeypatch)
    monkeypatch.setattr("embeddings.build_embedder", lambda s: _FakeEmbedder())
    monkeypatch.setattr("es_store.client.elasticsearch_client", lambda s: object())
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    from conf.settings import get_settings

    get_settings.cache_clear()
    from qa.webui.app import app

    with TestClient(app) as tc:
        yield tc


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_qa_stream_returns_sse_lines(client: TestClient) -> None:
    """不依赖真实 openai：mock `find_spec` 与 `stream_qa_events`。"""
    import json
    from unittest.mock import patch

    def fake_events(*a, **k):
        yield {"type": "start", "conversation_id": None, "offset_ms": 0.0}
        yield {
            "type": "done",
            "ok": True,
            "total_ms": 1.0,
            "ttft_ms": None,
            "timings": {},
            "text": "",
            "conversation_id": None,
        }

    with patch("importlib.util.find_spec", return_value=object()):
        with patch("qa.webui.app.stream_qa_events", fake_events):
            with client.stream(
                "POST",
                "/api/qa/stream",
                json={"query": "hi"},
            ) as r:
                assert r.status_code == 200
                assert "text/event-stream" in r.headers.get("content-type", "")
                body = "".join(r.iter_text())
                assert "data:" in body
                lines = [ln for ln in body.split("\n") if ln.startswith("data:")]
                assert len(lines) >= 1
                obj = json.loads(lines[0][5:].strip())
                assert obj["type"] == "start"
