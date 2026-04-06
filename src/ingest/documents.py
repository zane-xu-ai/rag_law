"""将 `TextChunk` 与向量组装为 ES `_source` 文档（与 c04 / `bulk_index_chunks` 约定一致）。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from chunking.split import TextChunk

from es_store.chunk_defaults import apply_chunk_source_defaults


def chunk_embedding_to_source(
    chunk: TextChunk,
    embedding: list[float],
    *,
    source_sha256: str = "",
) -> dict[str, Any]:
    """单条 chunk → 待索引文档 dict；不调用 ES。

    `source_sha256` 通常为**整文件** UTF-8 字节 SHA256（十六进制小写），同文件各 chunk 相同。
    """
    row: dict[str, Any] = {
        "text": chunk.text,
        "embedding": embedding,
        "source_file": chunk.source_file,
        "source_path": chunk.source_path or "",
        "chunk_index": chunk.chunk_index,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "source_doc_id": chunk.source_id or "",
        "mime_type": chunk.mime_type,
        "doc_type": chunk.doc_type,
        "domain": chunk.domain,
        "chunk_type": "text",
    }
    if source_sha256:
        row["source_sha256"] = source_sha256
    if chunk.extra:
        row["extra"] = chunk.extra
    return apply_chunk_source_defaults(row)


def sha256_utf8_file(path: Path) -> str:
    """对文件原始字节做 SHA256（与磁盘内容一致）。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()
