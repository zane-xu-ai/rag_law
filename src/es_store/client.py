"""Elasticsearch 客户端工厂（复用 `Settings.es_url` 与基本认证）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conf.settings import Settings


def elasticsearch_client(settings: Settings):
    """构造与 Server 8/9 兼容的 `Elasticsearch` 客户端。"""
    from elasticsearch import Elasticsearch

    kw: dict = {}
    user, password = settings.es_user, settings.es_password
    if user is not None and password is not None:
        kw["basic_auth"] = (user, password)
    return Elasticsearch(hosts=[settings.es_url], request_timeout=120, **kw)
