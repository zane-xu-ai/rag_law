"""遍历 `data/*.md` 并产出带每文件 `source_sha256` 的 chunk 流（与 `chunking.split.iter_chunks_for_data_dir` 参数对齐）。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Optional

from chunking.split import TextChunk, iter_file_chunks
from conf.settings import get_settings, project_root

from ingest.documents import sha256_utf8_file


def iter_chunks_for_data_dir_with_sha256(
    data_dir: Optional[Path] = None,
    *,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    root: Optional[Path] = None,
    boundary_aware: bool = False,
    overlap_floor: Optional[int] = None,
    overlap_ceiling: Optional[int] = None,
    max_boundary_scan: Optional[int] = None,
    boundary_priority_overlap: Optional[bool] = None,
    clamp_adjust_max_rounds: Optional[int] = None,
) -> Iterator[tuple[TextChunk, str]]:
    """与 `iter_chunks_for_data_dir` 相同遍历顺序；每个 chunk 附带该文件 `sha256.hexdigest()`。"""
    s = None
    if chunk_size is None or chunk_overlap is None:
        s = get_settings()
        chunk_size = chunk_size if chunk_size is not None else s.chunk_size
        chunk_overlap = chunk_overlap if chunk_overlap is not None else s.chunk_overlap
    eff_mb = max_boundary_scan
    eff_bpo = boundary_priority_overlap
    eff_car = clamp_adjust_max_rounds
    if boundary_aware:
        if s is None:
            s = get_settings()
        if overlap_floor is None:
            overlap_floor = s.chunk_overlap_floor
        if overlap_ceiling is None:
            overlap_ceiling = s.chunk_overlap_ceiling
        if eff_mb is None:
            eff_mb = s.chunk_boundary_max_scan
        if eff_bpo is None:
            eff_bpo = s.chunk_boundary_priority_overlap
        if eff_car is None:
            eff_car = s.chunk_boundary_clamp_adjust_max_rounds

    root = root if root is not None else project_root()
    base = data_dir if data_dir is not None else root / "data"
    if not base.is_dir():
        raise FileNotFoundError("数据目录不存在: %s" % base)

    for md in sorted(base.glob("*.md")):
        file_sha = sha256_utf8_file(md)
        for chunk in iter_file_chunks(
            md,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            root=root,
            boundary_aware=boundary_aware,
            overlap_floor=overlap_floor,
            overlap_ceiling=overlap_ceiling,
            max_boundary_scan=eff_mb,
            boundary_priority_overlap=eff_bpo,
            clamp_adjust_max_rounds=eff_car,
        ):
            yield chunk, file_sha


def load_chunks_with_sha256(
    data_dir: Optional[Path] = None,
    *,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    root: Optional[Path] = None,
    boundary_aware: bool = False,
    overlap_floor: Optional[int] = None,
    overlap_ceiling: Optional[int] = None,
    max_boundary_scan: Optional[int] = None,
    boundary_priority_overlap: Optional[bool] = None,
    clamp_adjust_max_rounds: Optional[int] = None,
) -> tuple[list[TextChunk], list[str]]:
    """返回 `(chunks, file_sha_per_chunk)`，两列表等长。"""
    pairs = list(
        iter_chunks_for_data_dir_with_sha256(
            data_dir,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            root=root,
            boundary_aware=boundary_aware,
            overlap_floor=overlap_floor,
            overlap_ceiling=overlap_ceiling,
            max_boundary_scan=max_boundary_scan,
            boundary_priority_overlap=boundary_priority_overlap,
            clamp_adjust_max_rounds=clamp_adjust_max_rounds,
        )
    )
    if not pairs:
        return [], []
    ch, sh = zip(*pairs)
    return list(ch), list(sh)
