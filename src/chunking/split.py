"""字符滑窗切分：单文本、单文件、`data/*.md` 目录遍历。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from conf.settings import get_settings, project_root

from chunking.boundary import iter_text_slices_boundary_aware


@dataclass
class TextChunk:
    """单块文本及元数据（供后续向量与 ES 使用）。"""

    text: str
    source_file: str
    chunk_index: int
    char_start: int
    char_end: int
    source_path: Optional[str] = None
    source_id: Optional[str] = None
    mime_type: str = "text/markdown"
    doc_type: str = "law_md"
    domain: str = "law"
    extra: Optional[dict[str, Any]] = field(default=None)


def iter_text_slices(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> Iterator[tuple[str, int, int]]:
    """
    对整段文本做字符滑窗，产出 (片段, char_start, char_end)。
    char_end 为 Python 切片意义下的结束下标（不包含），即 text[char_start:char_end] == 片段。
    空文本不产生任何片段。
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须小于 chunk_size")
    n = len(text)
    if n == 0:
        return
    step = chunk_size - chunk_overlap
    start = 0
    while start < n:
        end = min(start + chunk_size, n)
        yield text[start:end], start, end
        if end >= n:
            break
        start += step


def iter_chunks_for_text(
    full_text: str,
    *,
    source_file: str,
    source_path: Optional[str],
    chunk_size: int,
    chunk_overlap: int,
    mime_type: str = "text/markdown",
    doc_type: str = "law_md",
    domain: str = "law",
    boundary_aware: bool = False,
) -> Iterator[TextChunk]:
    """对已有字符串切分并附加元数据（单文件内 chunk_index 从 0 递增）。

    `boundary_aware=True` 时在滑窗初值上按句界（。！？；与换行等）微调首尾，见 `doc/chunk/句边界对齐切分.md`。
    """
    sid = source_path or source_file
    slicer = iter_text_slices_boundary_aware if boundary_aware else iter_text_slices
    for idx, (piece, c0, c1) in enumerate(
        slicer(full_text, chunk_size, chunk_overlap)
    ):
        yield TextChunk(
            text=piece,
            source_file=source_file,
            chunk_index=idx,
            char_start=c0,
            char_end=c1,
            source_path=source_path,
            source_id=sid,
            mime_type=mime_type,
            doc_type=doc_type,
            domain=domain,
            extra=None,
        )


def iter_file_chunks(
    md_path: Path,
    *,
    chunk_size: int,
    chunk_overlap: int,
    root: Optional[Path] = None,
    boundary_aware: bool = False,
) -> Iterator[TextChunk]:
    """
    读取单个 UTF-8 Markdown 文件并切分。
    `root` 用于计算 `source_path`（相对路径）；默认使用 `project_root()`。
    `boundary_aware=True` 时使用句边界对齐（见 `chunking.boundary`）。
    """
    root = root if root is not None else project_root()
    text = md_path.read_text(encoding="utf-8")
    try:
        rel = md_path.resolve().relative_to(root.resolve())
        source_path = rel.as_posix()
    except ValueError:
        source_path = md_path.as_posix()
    yield from iter_chunks_for_text(
        text,
        source_file=md_path.name,
        source_path=source_path,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        boundary_aware=boundary_aware,
    )


def iter_chunks_for_data_dir(
    data_dir: Optional[Path] = None,
    *,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    root: Optional[Path] = None,
    boundary_aware: bool = False,
) -> Iterator[TextChunk]:
    """
    遍历目录下所有 `*.md`（排序稳定），依次切分。

    若 `chunk_size` / `chunk_overlap` 未同时显式传入，则从 `conf.get_settings()` 读取缺失项。
    若任一为 None，则两者均从配置读取（避免与 settings 不一致）。
    """
    if chunk_size is None or chunk_overlap is None:
        s = get_settings()
        chunk_size = chunk_size if chunk_size is not None else s.chunk_size
        chunk_overlap = chunk_overlap if chunk_overlap is not None else s.chunk_overlap

    root = root if root is not None else project_root()
    base = data_dir if data_dir is not None else root / "data"
    if not base.is_dir():
        raise FileNotFoundError(f"数据目录不存在: {base}")

    for md in sorted(base.glob("*.md")):
        yield from iter_file_chunks(
            md,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            root=root,
            boundary_aware=boundary_aware,
        )


def load_all_chunks(
    data_dir: Optional[Path] = None,
    *,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    root: Optional[Path] = None,
    boundary_aware: bool = False,
) -> list[TextChunk]:
    """等价于 `list(iter_chunks_for_data_dir(...))`。"""
    return list(
        iter_chunks_for_data_dir(
            data_dir,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            root=root,
            boundary_aware=boundary_aware,
        )
    )
