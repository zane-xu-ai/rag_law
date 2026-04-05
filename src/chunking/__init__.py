"""字符滑窗切分（法律 Markdown 等）。"""

from chunking.split import (
    TextChunk,
    iter_chunks_for_data_dir,
    iter_chunks_for_text,
    iter_file_chunks,
    iter_text_slices,
    load_all_chunks,
)

__all__ = [
    "TextChunk",
    "iter_text_slices",
    "iter_chunks_for_text",
    "iter_file_chunks",
    "iter_chunks_for_data_dir",
    "load_all_chunks",
]
