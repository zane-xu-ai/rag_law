"""`es_store.client`：mock Elasticsearch 构造参数。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from conf.settings import get_settings


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, val in {
        "MODEL_API_KEY": "k",
        "MODEL_BASE_URL": "https://x/v1",
        "MODEL_NAME": "m",
        "ES_HOST": "localhost",
        "ES_PORT": "9200",
        "ES_INDEX": "test_index",
        "BGE_M3_PATH": "/models/bge",
        "CHUNK_SIZE": "800",
        "CHUNK_OVERLAP": "50",
        "RETRIEVAL_K": "5",
    }.items():
        monkeypatch.setenv(key, val)


def test_elasticsearch_client_hosts_and_no_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    get_settings.cache_clear()
    with patch("elasticsearch.Elasticsearch") as Es:
        from es_store.client import elasticsearch_client

        elasticsearch_client(get_settings())
        Es.assert_called_once()
        _, kwargs = Es.call_args
        assert kwargs["hosts"] == ["http://localhost:9200"]
        assert "basic_auth" not in kwargs


def test_elasticsearch_client_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    _base_env(monkeypatch)
    monkeypatch.setenv("ES_USER", "elastic")
    monkeypatch.setenv("ES_PASSWORD", "secret")
    get_settings.cache_clear()
    with patch("elasticsearch.Elasticsearch") as Es:
        from es_store.client import elasticsearch_client

        elasticsearch_client(get_settings())
        _, kwargs = Es.call_args
        assert kwargs.get("basic_auth") == ("elastic", "secret")
