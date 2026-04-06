"""`qa.webui.app`：健康检查与 SSE（mock `stream_qa_events` / `find_spec`）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from qa.webui.app import app

    return TestClient(app)


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
