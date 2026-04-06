"""Elasticsearch：chunk 索引 mapping、bulk 写入、kNN 检索。"""

from es_store.chunk_defaults import apply_chunk_source_defaults
from es_store.client import elasticsearch_client
from es_store.mapping import chunk_index_mappings
from es_store.store import EsChunkStore

__all__ = [
    "EsChunkStore",
    "apply_chunk_source_defaults",
    "chunk_index_mappings",
    "elasticsearch_client",
]
