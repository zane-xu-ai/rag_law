"""es_store.version_cleanup"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from es_store.version_cleanup import delete_chunks_not_matching_version


def test_delete_chunks_not_matching_version_builds_query() -> None:
    client = MagicMock()
    client.delete_by_query.return_value = {"deleted": 3}
    out = delete_chunks_not_matching_version(client, "my-index", "1.1.7")
    assert out["deleted"] == 3
    client.delete_by_query.assert_called_once()
    call_kw = client.delete_by_query.call_args.kwargs
    assert call_kw["index"] == "my-index"
    assert call_kw["refresh"] is True
    assert call_kw["conflicts"] == "proceed"
    q = call_kw["query"]["bool"]["must_not"][0]["term"]["chunk_version"]
    assert q == "1.1.7"


def test_delete_chunks_not_matching_version_rejects_empty() -> None:
    with pytest.raises(ValueError, match="current_version"):
        delete_chunks_not_matching_version(MagicMock(), "x", "")
