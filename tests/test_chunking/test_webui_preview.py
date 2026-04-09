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
    monkeypatch.setenv("CHUNK_OVERLAP", "100")
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
    ov = data["summary"]["overlap_between_adjacent"]
    ch = data["display"]["chunks"]
    assert ch[0]["overlap_prev"] == 0 and ch[0]["overlap_next"] == ov[0]
    assert ch[1]["overlap_prev"] == ov[0] and ch[1]["overlap_next"] == ov[1]
    assert ch[2]["overlap_prev"] == ov[1] and ch[2]["overlap_next"] == 0


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
    summ = r.json()["summary"]
    assert summ["boundary_aware"] is True
    assert summ["overlap_floor_effective"] == 0
    assert summ["overlap_ceiling_effective"] == 0
    assert "chunk_size 是滑窗初值长度上限" in summ["boundary_length_note"]


def test_preview_boundary_overlap_effective_follows_request_not_global_chunk_overlap(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未配置 CHUNK_OVERLAP_MIN/MAX 时，重叠区间应与表单 chunk_overlap 一致（不因全局 CHUNK_OVERLAP 更小而压扁）。"""
    monkeypatch.setenv("CHUNK_OVERLAP", "50")
    from conf.settings import get_settings

    get_settings.cache_clear()
    r = client.post(
        "/api/preview",
        json={
            "text": "x" * 800,
            "chunk_size": 200,
            "chunk_overlap": 100,
            "boundary_aware": True,
        },
    )
    assert r.status_code == 200
    summ = r.json()["summary"]
    assert summ["overlap_floor_effective"] == 100
    assert summ["overlap_ceiling_effective"] == 100


def test_preview_wrong_content_type(client: TestClient) -> None:
    r = client.post(
        "/api/preview",
        content=b"not json",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 415


def test_preview_compare_semantic_returns_two_payloads(client: TestClient) -> None:
    """对比模式：boundary 无语义合并，semantic_merged 启用合并。"""
    r = client.post(
        "/api/preview",
        json={
            "text": "a" * 50,
            "chunk_size": 20,
            "chunk_overlap": 0,
            "boundary_aware": False,
            "compare_semantic": True,
            "semantic_merge_threshold": 0.0,
            "semantic_merge_min_chars": 25,
            "semantic_merge_max_chars": 2200,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "comparison"
    assert data["boundary"]["summary"]["semantic_merge_enabled"] is False
    assert data["semantic_merged"]["summary"]["semantic_merge_enabled"] is True
    assert data["boundary"]["summary"]["chunk_count"] == 3
    assert data["semantic_merged"]["summary"]["chunk_count"] < 3
    assert "semantic_merge_note" in data["semantic_merged"]["summary"]
