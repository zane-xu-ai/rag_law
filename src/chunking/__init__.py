"""字符滑窗切分（法律 Markdown 等）。"""

from chunking.boundary import (
    ACCEPTABLE_BOUNDARY_CHARS,
    BOUNDARY_CHARS,
    DEFAULT_MAX_PROBE,
    WEAK_BOUNDARY_CHARS,
    adjust_end,
    adjust_end_extended,
    adjust_start,
    adjust_start_extended,
    is_acceptable_head,
    is_acceptable_tail,
    iter_boundary_aware_diag_rows,
    iter_text_slices_boundary_aware,
)
from chunking.split import (
    TextChunk,
    iter_chunks_for_data_dir,
    iter_chunks_for_text,
    iter_file_chunks,
    iter_text_slices,
    load_all_chunks,
    semantic_merge_chunks,
)

__all__ = [
    "BOUNDARY_CHARS",
    "WEAK_BOUNDARY_CHARS",
    "ACCEPTABLE_BOUNDARY_CHARS",
    "DEFAULT_MAX_PROBE",
    "TextChunk",
    "adjust_end",
    "adjust_end_extended",
    "adjust_start",
    "adjust_start_extended",
    "is_acceptable_head",
    "is_acceptable_tail",
    "iter_text_slices",
    "iter_text_slices_boundary_aware",
    "iter_boundary_aware_diag_rows",
    "iter_chunks_for_text",
    "iter_file_chunks",
    "iter_chunks_for_data_dir",
    "load_all_chunks",
    "semantic_merge_chunks",
]
