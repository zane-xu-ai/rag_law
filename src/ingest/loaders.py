"""遍历 `data/*.md` 并产出带每文件 `source_sha256` 的 chunk 流（与 `chunking.split.iter_chunks_for_data_dir` 参数对齐）。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Optional

from chunking.split import TextChunk, iter_file_chunks
from conf.settings import get_settings, project_root

from ingest.documents import sha256_utf8_file


def _resolve_chunking_params(
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
    semantic_merge_enabled: bool = False,
    semantic_merge_threshold: float = 0.82,
    semantic_merge_min_chars: int = 220,
    semantic_merge_max_chars: int = 2200,
) -> tuple[
    int,
    int,
    Path,
    bool,
    Optional[int],
    Optional[int],
    Optional[int],
    Optional[bool],
    Optional[int],
    bool,
    float,
    int,
    int,
]:
    """与 `iter_chunks_for_data_dir_with_sha256` 相同的配置解析。"""
    s = None
    if chunk_size is None or chunk_overlap is None:
        s = get_settings()
        chunk_size = chunk_size if chunk_size is not None else s.chunk_size
        chunk_overlap = chunk_overlap if chunk_overlap is not None else s.chunk_overlap
    eff_mb = max_boundary_scan
    eff_bpo = boundary_priority_overlap
    eff_car = clamp_adjust_max_rounds
    eff_sem_enabled = semantic_merge_enabled
    eff_sem_th = semantic_merge_threshold
    eff_sem_min = semantic_merge_min_chars
    eff_sem_max = semantic_merge_max_chars
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
    return (
        chunk_size,
        chunk_overlap,
        root,
        boundary_aware,
        overlap_floor,
        overlap_ceiling,
        eff_mb,
        eff_bpo,
        eff_car,
        eff_sem_enabled,
        eff_sem_th,
        eff_sem_min,
        eff_sem_max,
    )


def _iter_chunks_for_md_files_with_sha256(
    md_files: list[Path],
    *,
    chunk_size: int,
    chunk_overlap: int,
    root: Path,
    boundary_aware: bool,
    overlap_floor: Optional[int],
    overlap_ceiling: Optional[int],
    eff_mb: Optional[int],
    eff_bpo: Optional[bool],
    eff_car: Optional[int],
    semantic_merge_enabled: bool,
    semantic_merge_threshold: float,
    semantic_merge_min_chars: int,
    semantic_merge_max_chars: int,
) -> Iterator[tuple[TextChunk, str]]:
    for md in md_files:
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
            semantic_merge_enabled=semantic_merge_enabled,
            semantic_merge_threshold=semantic_merge_threshold,
            semantic_merge_min_chars=semantic_merge_min_chars,
            semantic_merge_max_chars=semantic_merge_max_chars,
        ):
            yield chunk, file_sha


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
    semantic_merge_enabled: bool = False,
    semantic_merge_threshold: float = 0.82,
    semantic_merge_min_chars: int = 220,
    semantic_merge_max_chars: int = 2200,
) -> Iterator[tuple[TextChunk, str]]:
    """与 `iter_chunks_for_data_dir` 相同遍历顺序；每个 chunk 附带该文件 `sha256.hexdigest()`。"""
    (
        chunk_size,
        chunk_overlap,
        root,
        boundary_aware,
        overlap_floor,
        overlap_ceiling,
        eff_mb,
        eff_bpo,
        eff_car,
        eff_sem_enabled,
        eff_sem_th,
        eff_sem_min,
        eff_sem_max,
    ) = _resolve_chunking_params(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        root=root,
        boundary_aware=boundary_aware,
        overlap_floor=overlap_floor,
        overlap_ceiling=overlap_ceiling,
        max_boundary_scan=max_boundary_scan,
        boundary_priority_overlap=boundary_priority_overlap,
        clamp_adjust_max_rounds=clamp_adjust_max_rounds,
        semantic_merge_enabled=semantic_merge_enabled,
        semantic_merge_threshold=semantic_merge_threshold,
        semantic_merge_min_chars=semantic_merge_min_chars,
        semantic_merge_max_chars=semantic_merge_max_chars,
    )
    base = data_dir if data_dir is not None else root / "data"
    if not base.is_dir():
        raise FileNotFoundError("数据目录不存在: %s" % base)

    md_files = sorted(base.glob("*.md"))
    yield from _iter_chunks_for_md_files_with_sha256(
        md_files,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        root=root,
        boundary_aware=boundary_aware,
        overlap_floor=overlap_floor,
        overlap_ceiling=overlap_ceiling,
        eff_mb=eff_mb,
        eff_bpo=eff_bpo,
        eff_car=eff_car,
        semantic_merge_enabled=eff_sem_enabled,
        semantic_merge_threshold=eff_sem_th,
        semantic_merge_min_chars=eff_sem_min,
        semantic_merge_max_chars=eff_sem_max,
    )


def iter_chunks_for_paths_with_sha256(
    paths: list[Path],
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
    semantic_merge_enabled: bool = False,
    semantic_merge_threshold: float = 0.82,
    semantic_merge_min_chars: int = 220,
    semantic_merge_max_chars: int = 2200,
) -> Iterator[tuple[TextChunk, str]]:
    """按给定 Markdown 文件路径列表切分（排序后）；与目录遍历语义一致。"""
    if not paths:
        return
    md_files: list[Path] = []
    for p in paths:
        rp = p.expanduser().resolve()
        if not rp.is_file():
            raise FileNotFoundError("不是文件或不存在: %s" % p)
        if rp.suffix.lower() != ".md":
            raise ValueError("仅支持 .md 文件: %s" % p)
        md_files.append(rp)
    md_files = sorted(md_files)
    (
        chunk_size,
        chunk_overlap,
        root,
        boundary_aware,
        overlap_floor,
        overlap_ceiling,
        eff_mb,
        eff_bpo,
        eff_car,
        eff_sem_enabled,
        eff_sem_th,
        eff_sem_min,
        eff_sem_max,
    ) = _resolve_chunking_params(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        root=root,
        boundary_aware=boundary_aware,
        overlap_floor=overlap_floor,
        overlap_ceiling=overlap_ceiling,
        max_boundary_scan=max_boundary_scan,
        boundary_priority_overlap=boundary_priority_overlap,
        clamp_adjust_max_rounds=clamp_adjust_max_rounds,
        semantic_merge_enabled=semantic_merge_enabled,
        semantic_merge_threshold=semantic_merge_threshold,
        semantic_merge_min_chars=semantic_merge_min_chars,
        semantic_merge_max_chars=semantic_merge_max_chars,
    )
    yield from _iter_chunks_for_md_files_with_sha256(
        md_files,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        root=root,
        boundary_aware=boundary_aware,
        overlap_floor=overlap_floor,
        overlap_ceiling=overlap_ceiling,
        eff_mb=eff_mb,
        eff_bpo=eff_bpo,
        eff_car=eff_car,
        semantic_merge_enabled=eff_sem_enabled,
        semantic_merge_threshold=eff_sem_th,
        semantic_merge_min_chars=eff_sem_min,
        semantic_merge_max_chars=eff_sem_max,
    )


def load_chunks_with_sha256(
    data_dir: Optional[Path] = None,
    *,
    md_paths: Optional[list[Path]] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    root: Optional[Path] = None,
    boundary_aware: bool = False,
    overlap_floor: Optional[int] = None,
    overlap_ceiling: Optional[int] = None,
    max_boundary_scan: Optional[int] = None,
    boundary_priority_overlap: Optional[bool] = None,
    clamp_adjust_max_rounds: Optional[int] = None,
    semantic_merge_enabled: bool = False,
    semantic_merge_threshold: float = 0.82,
    semantic_merge_min_chars: int = 220,
    semantic_merge_max_chars: int = 2200,
) -> tuple[list[TextChunk], list[str]]:
    """返回 `(chunks, file_sha_per_chunk)`，两列表等长。

    若传入 ``md_paths``，则只处理这些文件（忽略 ``data_dir``）；否则扫描 ``data_dir`` 下 ``*.md``。
    """
    if md_paths is not None:
        pairs = list(
            iter_chunks_for_paths_with_sha256(
                md_paths,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                root=root,
                boundary_aware=boundary_aware,
                overlap_floor=overlap_floor,
                overlap_ceiling=overlap_ceiling,
                max_boundary_scan=max_boundary_scan,
                boundary_priority_overlap=boundary_priority_overlap,
                clamp_adjust_max_rounds=clamp_adjust_max_rounds,
                semantic_merge_enabled=semantic_merge_enabled,
                semantic_merge_threshold=semantic_merge_threshold,
                semantic_merge_min_chars=semantic_merge_min_chars,
                semantic_merge_max_chars=semantic_merge_max_chars,
            )
        )
    else:
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
                semantic_merge_enabled=semantic_merge_enabled,
                semantic_merge_threshold=semantic_merge_threshold,
                semantic_merge_min_chars=semantic_merge_min_chars,
                semantic_merge_max_chars=semantic_merge_max_chars,
            )
        )
    if not pairs:
        return [], []
    ch, sh = zip(*pairs)
    return list(ch), list(sh)
