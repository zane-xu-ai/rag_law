"""chunking.webui：方案 D 文档分段预览 API。"""

from __future__ import annotations

import importlib
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_webui_mod = importlib.import_module("chunking.webui.app")
app = _webui_mod.app
clear_document_segmentation_pipeline_cache = _webui_mod.clear_document_segmentation_pipeline_cache


@pytest.fixture(autouse=True)
def _webui_min_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.fixture(autouse=True)
def _clear_doc_seg_pipeline() -> None:
    clear_document_segmentation_pipeline_cache()
    yield
    clear_document_segmentation_pipeline_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_document_segmentation_status(client: TestClient) -> None:
    r = client.get("/api/document-segmentation/status")
    assert r.status_code == 200
    j = r.json()
    assert "modelscope_import_ok" in j
    assert "document_segmentation_path" in j
    assert "path_exists" in j


def test_preview_document_segmentation_json_fake_pipeline(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "fake_model_dir"
    base.mkdir()

    class FakeP:
        def __call__(self, x: str) -> list[str]:
            if len(x) >= 10:
                return [x[:5], x[5:]]
            return [x]

    monkeypatch.setattr(_webui_mod, "_resolve_model_dir_for_doc_seg", lambda _mp: base)
    monkeypatch.setattr(
        _webui_mod,
        "_get_or_build_document_segmentation_pipeline",
        lambda _p: FakeP(),
    )

    r = client.post(
        "/api/preview-document-segmentation",
        json={
            "text": "abcdefghij",
            "min_chars": 0,
            "max_chars": 100,
            "split_overlap": 0,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "single"
    assert data["summary"]["method"] == "document_segmentation_d"
    assert data["summary"]["chunk_count"] == 2
    assert data["summary"]["doc_segmentation_max_chars"] == 100
    assert len(data["display"]["chunks"]) == 2


def test_preview_document_segmentation_requires_model_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DOCUMENT_SEGMENTATION_PATH", raising=False)
    from conf.settings import get_settings

    get_settings.cache_clear()
    r = client.post(
        "/api/preview-document-segmentation",
        json={"text": "abc", "min_chars": 0, "max_chars": 50, "split_overlap": 0},
    )
    assert r.status_code == 400
    assert "DOCUMENT_SEGMENTATION_PATH" in r.json()["detail"]


def test_preview_document_segmentation_overlap_invalid(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "m2"
    base.mkdir()
    monkeypatch.setattr(_webui_mod, "_resolve_model_dir_for_doc_seg", lambda _mp: base)
    monkeypatch.setattr(
        _webui_mod,
        "_get_or_build_document_segmentation_pipeline",
        lambda _p: object(),
    )
    r = client.post(
        "/api/preview-document-segmentation",
        json={
            "text": "a",
            "model_path": str(base),
            "min_chars": 0,
            "max_chars": 10,
            "split_overlap": 10,
        },
    )
    assert r.status_code == 422


def test_preview_document_segmentation_multipart(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    base = tmp_path / "m3"
    base.mkdir()

    class FakeP:
        def __call__(self, x: str) -> list[str]:
            return [x[:2], x[2:]] if len(x) >= 4 else [x]

    monkeypatch.setattr(_webui_mod, "_resolve_model_dir_for_doc_seg", lambda _mp: base)
    monkeypatch.setattr(
        _webui_mod,
        "_get_or_build_document_segmentation_pipeline",
        lambda _p: FakeP(),
    )
    raw = "abcd".encode("utf-8")
    r = client.post(
        "/api/preview-document-segmentation",
        files={"file": ("t.md", io.BytesIO(raw), "text/plain")},
        data={
            "text": "",
            "min_chars": "0",
            "max_chars": "50",
            "split_overlap": "0",
        },
    )
    assert r.status_code == 200
    assert r.json()["summary"]["total_chars"] == 4
