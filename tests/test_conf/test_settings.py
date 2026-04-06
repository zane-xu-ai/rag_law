"""对应 `src/conf/settings.py`：环境与校验行为（不依赖本机真实 `.env` 内容）。

目录命名为 `test_conf`（而非 `tests/conf`），避免与可导入包 `conf` 同名导致 pytest 将 `tests/` 加入 path 时遮蔽 `src/conf`。
"""

from __future__ import annotations

import pytest

from conf.settings import Settings, get_settings, project_root


def _base_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    """写入一组完整环境变量，避免测试机上的 `.env` 干扰断言。"""
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


def test_get_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    s = get_settings()
    assert s.model_api_key == "test-model-api-key"
    assert s.model_name == "qwen-test"
    assert s.es_index == "test_index"
    assert s.chunk_size == 800
    assert s.chunk_overlap == 50
    assert s.retrieval_k == 5
    assert s.bge_m3_path == "/opt/models/bge-m3"
    assert s.embedding_batch_size == 32


def test_openai_api_key_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-alias")
    s = get_settings()
    assert s.model_api_key == "sk-openai-alias"


def test_parent_chunk_size_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch, CHUNK_SIZE="900")  # will override
    monkeypatch.delenv("CHUNK_SIZE", raising=False)
    monkeypatch.setenv("PARENT_CHUNK_SIZE", "1200")
    s = get_settings()
    assert s.chunk_size == 1200


def test_overlap_must_be_less_than_chunk_size(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch, CHUNK_SIZE="100", CHUNK_OVERLAP="100")
    with pytest.raises(ValueError, match="CHUNK_OVERLAP"):
        get_settings()


def test_chunk_overlap_min_must_not_exceed_chunk_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _base_env(monkeypatch, CHUNK_OVERLAP="50", CHUNK_OVERLAP_MIN="60")
    with pytest.raises(ValueError, match="CHUNK_OVERLAP_MIN"):
        get_settings()


def test_chunk_overlap_floor_uses_min_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch, CHUNK_OVERLAP="100", CHUNK_OVERLAP_MIN="60")
    get_settings.cache_clear()
    assert get_settings().chunk_overlap_floor == 60


def test_es_url_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch, ES_USE_SSL="false")
    s = get_settings()
    assert s.es_url == "http://localhost:9200"


def test_es_url_https_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch, ES_USE_SSL="true")
    s = get_settings()
    assert s.es_url == "https://localhost:9200"


def test_es_url_with_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("ES_USER", "elastic")
    monkeypatch.setenv("ES_PASSWORD", "p@ss:word")
    s = get_settings()
    assert s.es_url == "http://elastic:p%40ss%3Aword@localhost:9200"


def test_es_scheme_matches_es_use_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch, ES_USE_SSL="true")
    assert get_settings().es_scheme == "https"
    monkeypatch.setenv("ES_USE_SSL", "false")
    get_settings.cache_clear()
    assert get_settings().es_scheme == "http"


def test_project_root_points_to_repo_root() -> None:
    root = project_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "conf" / "settings.py").is_file()


def test_settings_direct_instantiation(monkeypatch: pytest.MonkeyPatch) -> None:
    """绕过 `get_settings` 缓存，直接构造以覆盖更多路径。"""
    _base_env(monkeypatch, EMBEDDING_BATCH_SIZE="16")
    s = Settings()
    assert s.embedding_batch_size == 16
