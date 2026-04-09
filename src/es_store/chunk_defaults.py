"""chunk `_source` 应用层默认值（ES mapping 无 default；与 `TextChunk` 对齐）。"""

from __future__ import annotations

from typing import Any

# 与 chunking.split.TextChunk 默认一致
DEFAULT_CHUNK_TYPE = "text"
DEFAULT_MIME_TYPE = "text/markdown"
DEFAULT_DOC_TYPE = "law_md"
DEFAULT_DOMAIN = "law"


def apply_chunk_source_defaults(doc: dict[str, Any]) -> dict[str, Any]:
    """为单条待索引文档补齐可选字段；调用方已赋值的键不会被覆盖。

    用于 `bulk_index_chunks` 及笔记本/脚本显式组装文档时保持一致。
    """
    out = dict(doc)
    if "chunk_type" not in out:
        out["chunk_type"] = DEFAULT_CHUNK_TYPE
    if "mime_type" not in out:
        out["mime_type"] = DEFAULT_MIME_TYPE
    if "doc_type" not in out:
        out["doc_type"] = DEFAULT_DOC_TYPE
    if "domain" not in out:
        out["domain"] = DEFAULT_DOMAIN
    if "source_path" not in out:
        out["source_path"] = ""
    if "source_doc_id" not in out:
        out["source_doc_id"] = ""
    if "source_sha256" not in out:
        out["source_sha256"] = ""
    if "source_oss_url" not in out:
        out["source_oss_url"] = ""
    if "chunk_version" not in out:
        out["chunk_version"] = ""
    return out
