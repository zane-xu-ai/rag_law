"""入库：`data/*.md` → chunk → 向量 → ES 文档组装。"""

from ingest.documents import chunk_embedding_to_source, sha256_utf8_file
from ingest.loaders import (
    iter_chunks_for_data_dir_with_sha256,
    iter_chunks_for_paths_with_sha256,
    load_chunks_with_sha256,
)

__all__ = [
    "chunk_embedding_to_source",
    "iter_chunks_for_data_dir_with_sha256",
    "iter_chunks_for_paths_with_sha256",
    "load_chunks_with_sha256",
    "sha256_utf8_file",
]
