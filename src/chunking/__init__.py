"""字符滑窗切分（法律 Markdown 等）。"""

from chunking.boundary import (
    BOUNDARY_CHARS,
    DEFAULT_MAX_PROBE,
    WEAK_BOUNDARY_CHARS,
    adjust_end,
    adjust_start,
    iter_text_slices_boundary_aware,
)
from chunking.split import (
    TextChunk,
    iter_chunks_for_data_dir,
    iter_chunks_for_text,
    iter_file_chunks,
    iter_text_slices,
    load_all_chunks,
)

__all__ = [
    "BOUNDARY_CHARS",
    "WEAK_BOUNDARY_CHARS",
    "DEFAULT_MAX_PROBE",
    "TextChunk",
    "adjust_end",
    "adjust_start",
    "iter_text_slices",
    "iter_text_slices_boundary_aware",
    "iter_chunks_for_text",
    "iter_file_chunks",
    "iter_chunks_for_data_dir",
    "load_all_chunks",
]
