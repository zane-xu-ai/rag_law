"""`conf.monitor`：JSONL 与可选 ES 索引。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conf.monitor import build_qa_monitor_document, write_qa_monitor_record
from conf.settings import get_settings


def _minimal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "MODEL_API_KEY": "k",
        "MODEL_BASE_URL": "https://example.com/v1",
        "MODEL_NAME": "m",
        "BGE_M3_PATH": "/models/bge",
        "MONITOR_LOG_FILE": "",
    }.items():
        monkeypatch.setenv(key, value)


def test_build_qa_monitor_document_has_core_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env(monkeypatch)
    get_settings.cache_clear()
    s = get_settings()
    doc = build_qa_monitor_document(
        settings=s,
        query="hi",
        timings={"embed_query": 1.0, "es_search_knn": 2.0},
        k_eff=5,
        hit_count=3,
        total_ms=100.0,
        ttft_ms=40.0,
        rag_prefill_ms=50.0,
        llm_total_ms=45.0,
        ok=True,
        conversation_id=None,
        max_tokens=2048,
    )
    assert doc["service"] == "rag-law-qa"
    assert doc["event"] == "qa_request"
    assert doc["retrieval_k"] == 5
    assert doc["retrieval_hit_count"] == 3
    assert doc["embed_query_ms"] == 1.0
    assert doc["es_search_knn_ms"] == 2.0
    assert doc["query_len"] == 2
    assert "query_fp" in doc
    assert "@timestamp" in doc


def test_write_qa_monitor_record_jsonl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "m.log"
    monkeypatch.setenv("MODEL_API_KEY", "k")
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("MODEL_NAME", "m")
    monkeypatch.setenv("BGE_M3_PATH", "/models/bge")
    monkeypatch.setenv("MONITOR_LOG_FILE", str(log_path))
    get_settings.cache_clear()
    s = get_settings()
    rec = {"@timestamp": "t", "x": 1}
    write_qa_monitor_record(s, es_client=None, record=rec)
    assert log_path.read_text(encoding="utf-8").strip() == json.dumps(rec, ensure_ascii=False)


class _FakeEs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def index(self, *, index: str, document: dict[str, Any], refresh: bool) -> None:
        self.calls.append((index, document))


def test_write_qa_monitor_record_es_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _minimal_env(monkeypatch)
    monkeypatch.setenv("MONITOR_ES_ENABLED", "true")
    monkeypatch.setenv("MONITOR_ES_INDEX", "rag-law-monitor")
    get_settings.cache_clear()
    s = get_settings()
    fake = _FakeEs()
    rec = {"@timestamp": "t", "ok": True}
    write_qa_monitor_record(s, es_client=fake, record=rec)
    assert fake.calls == [("rag-law-monitor", rec)]


class _BrokenEs:
    def index(self, **kw: Any) -> None:
        raise RuntimeError("boom")


def test_write_qa_monitor_record_es_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _minimal_env(monkeypatch)
    monkeypatch.setenv("MONITOR_ES_ENABLED", "true")
    get_settings.cache_clear()
    s = get_settings()
    write_qa_monitor_record(s, es_client=_BrokenEs(), record={"ok": True})
