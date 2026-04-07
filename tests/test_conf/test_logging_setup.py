"""`conf.logging_setup`：configure_logging 幂等与文件 sink。"""

from __future__ import annotations

import pytest

from conf.logging_setup import configure_logging, reset_logging_for_tests
from conf.settings import Settings, get_settings


def _base_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    base: dict[str, str] = {
        "MODEL_API_KEY": "test-model-api-key",
        "MODEL_BASE_URL": "https://dashscope.example.com/compatible-mode/v1",
        "MODEL_NAME": "qwen-test",
        "ES_HOST": "localhost",
        "ES_PORT": "9200",
        "ES_INDEX": "test_index",
        "BGE_M3_PATH": "/opt/models/bge-m3",
        "CHUNK_SIZE": "800",
        "CHUNK_OVERLAP": "50",
        "RETRIEVAL_K": "5",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PARENT_CHUNK_SIZE", raising=False)
    monkeypatch.delenv("ES_USER", raising=False)
    monkeypatch.delenv("ES_PASSWORD", raising=False)


def test_configure_logging_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch, LOG_LEVEL="WARNING")
    get_settings.cache_clear()
    s = get_settings()
    reset_logging_for_tests()
    configure_logging(s)
    configure_logging(s)
    reset_logging_for_tests()


def test_configure_logging_writes_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    log_file = tmp_path / "out.log"
    _base_env(monkeypatch, LOG_LEVEL="INFO", LOG_FILE=str(log_file))
    get_settings.cache_clear()
    s = get_settings()
    reset_logging_for_tests()
    configure_logging(s)
    from loguru import logger

    logger.info("hello_logging_test")
    txt = log_file.read_text(encoding="utf-8")
    assert "hello_logging_test" in txt
    reset_logging_for_tests()


def test_log_level_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch, LOG_LEVEL="not-a-level")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        Settings()


def test_log_file_resolved_relative_to_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch, LOG_FILE="logs/x.log")
    get_settings.cache_clear()
    s = get_settings()
    assert s.log_file_resolved is not None
    assert s.log_file_resolved.name == "x.log"
    assert "logs" in s.log_file_resolved.parts
