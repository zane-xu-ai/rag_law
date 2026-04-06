"""chunking.webui FastAPI /api/preview。"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from chunking.webui.app import app


@pytest.fixture(autouse=True)
def _webui_min_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """预览在 boundary_aware 时会读 get_settings().chunk_overlap_floor，需完整必填项。"""
    monkeypatch.setenv("MODEL_API_KEY", "test-model-api-key")
    monkeypatch.setenv("MODEL_BASE_URL", "https://dashscope.example.com/compatible-mode/v1")
    monkeypatch.setenv("MODEL_NAME", "qwen-test")
    monkeypatch.setenv("BGE_M3_PATH", "/opt/models/bge-m3")
    monkeypatch.setenv("ES_HOST", "localhost")
    monkeypatch.setenv("ES_PORT", "9200")
    monkeypatch.setenv("ES_INDEX", "test_index")
    monkeypatch.setenv("CHUNK_SIZE", "800")
    monkeypatch.setenv("CHUNK_OVERLAP", "50")
    monkeypatch.setenv("RETRIEVAL_K", "5")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_index_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Chunking" in r.text


def test_preview_json_short_full_mode(client: TestClient) -> None:
    r = client.post(
        "/api/preview",
        json={"text": "abcdefghij", "chunk_size": 4, "chunk_overlap": 1},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["chunk_count"] == 3
    assert data["summary"]["total_chars"] == 10
    assert data["summary"]["boundary_aware"] is False
    assert data["display"]["mode"] == "full"
    assert len(data["display"]["chunks"]) == 3
    assert data["display"]["chunks"][0]["section"] == "all"


def test_preview_overlap_invalid(client: TestClient) -> None:
    r = client.post(
        "/api/preview",
        json={"text": "abc", "chunk_size": 3, "chunk_overlap": 3},
    )
    assert r.status_code == 422


def test_preview_truncated_over_15_chunks(client: TestClient) -> None:
    # 100 字符，size=4 overlap=0 → 25 块
    text = "a" * 100
    r = client.post(
        "/api/preview",
        json={"text": text, "chunk_size": 4, "chunk_overlap": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["chunk_count"] == 25
    assert data["display"]["mode"] == "truncated"
    assert data["display"]["total_chunks"] == 25
    assert len(data["display"]["chunks"]) == 15
    assert data["display"]["omitted_message"]
    assert data["display"]["chunks"][0]["section"] == "first"
    assert data["display"]["chunks"][-1]["section"] == "last"


def test_preview_multipart_file_utf8(client: TestClient) -> None:
    raw = "你好\n\n世界".encode("utf-8")
    r = client.post(
        "/api/preview",
        files={"file": ("t.txt", io.BytesIO(raw), "text/plain")},
        data={"text": "", "chunk_size": "2", "chunk_overlap": "0"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["total_chars"] == 6
    assert data["summary"]["source_paragraphs"] == 2


def test_preview_boundary_aware_json(client: TestClient) -> None:
    r = client.post(
        "/api/preview",
        json={
            "text": "abc。def",
            "chunk_size": 4,
            "chunk_overlap": 0,
            "boundary_aware": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["summary"]["boundary_aware"] is True


def test_preview_wrong_content_type(client: TestClient) -> None:
    r = client.post(
        "/api/preview",
        content=b"not json",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 415
