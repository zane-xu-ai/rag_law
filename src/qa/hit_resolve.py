"""按当前 ``Settings`` 从本地源文件重算块，使 QA 上下文与 ``.env`` 切分策略一致。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chunking.split import TextChunk
from conf.settings import project_root
from embeddings.base import EmbeddingBackend
from ingest.loaders import iter_chunks_in_memory_like_ingest


def _read_utf8_under_root(root: Path, source_path: str) -> str | None:
    if not (source_path or "").strip():
        return None
    rel = Path(source_path)
    if rel.is_absolute():
        return None
    full = (root / rel).resolve()
    try:
        full.relative_to(root.resolve())
    except ValueError:
        return None
    if not full.is_file():
        return None
    return full.read_text(encoding="utf-8")


def _pick_chunk_for_hit(
    chunks: list[TextChunk],
    *,
    char_start: Any,
    char_end: Any,
    chunk_index: Any,
) -> TextChunk | None:
    if not chunks:
        return None
    cs: int | None = None
    ce: int | None = None
    try:
        if char_start is not None:
            cs = int(char_start)
        if char_end is not None:
            ce = int(char_end)
    except (TypeError, ValueError):
        cs, ce = None, None

    if cs is not None and ce is not None and ce > cs:
        best: TextChunk | None = None
        best_ov = -1
        for c in chunks:
            lo = max(cs, c.char_start)
            hi = min(ce, c.char_end)
            ov = max(0, hi - lo)
            if ov > best_ov:
                best_ov = ov
                best = c
            elif ov == best_ov and ov > 0 and best is not None and c.chunk_index < best.chunk_index:
                best = c
        if best is not None and best_ov > 0:
            return best

    try:
        idx = int(chunk_index) if chunk_index is not None else None
    except (TypeError, ValueError):
        idx = None
    if idx is not None and 0 <= idx < len(chunks):
        return chunks[idx]

    return chunks[0]


def resolve_hit_source_text_from_settings(
    source: dict[str, Any],
    *,
    settings: Any,
    embedding_backend: EmbeddingBackend | None,
    root: Path | None = None,
) -> dict[str, Any]:
    """若开启 ``qa_resolve_chunks_from_source`` 且能读取 ``source_path``，用与入库相同的切分重算正文。

    句边界与重叠夹紧由 ``CHUNK_BOUNDARY_AWARE`` 与 ``CHUNK_OVERLAP_*`` 等控制，语义合并由
    ``CHUNK_SEMANTIC_MERGE_*`` 控制（embedding 模式需传入 ``embedding_backend``）。
    """
    if not getattr(settings, "qa_resolve_chunks_from_source", False):
        return source
    root = root if root is not None else project_root()
    sp = source.get("source_path")
    sp_str = str(sp).strip() if sp is not None else ""
    full = _read_utf8_under_root(root, sp_str)
    if full is None:
        return source

    merge_embedder: EmbeddingBackend | None = None
    if (
        getattr(settings, "chunk_semantic_merge_enabled", False)
        and getattr(settings, "chunk_semantic_merge_similarity", "char_ngram") == "embedding"
    ):
        merge_embedder = embedding_backend

    sf = source.get("source_file") or Path(sp_str).name
    chunks = list(
        iter_chunks_in_memory_like_ingest(
            full,
            source_file=str(sf),
            source_path=sp_str or None,
            embedding_backend=merge_embedder,
        )
    )
    picked = _pick_chunk_for_hit(
        chunks,
        char_start=source.get("char_start"),
        char_end=source.get("char_end"),
        chunk_index=source.get("chunk_index"),
    )
    if picked is None:
        return source

    out = dict(source)
    out["text"] = picked.text
    out["chunk_index"] = picked.chunk_index
    out["char_start"] = picked.char_start
    out["char_end"] = picked.char_end
    return out


def apply_hit_resolve_to_hits(
    hits: list[dict[str, Any]],
    *,
    settings: Any,
    embedding_backend: EmbeddingBackend | None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    if not hits or not getattr(settings, "qa_resolve_chunks_from_source", False):
        return hits
    out: list[dict[str, Any]] = []
    for h in hits:
        src = h.get("source") or {}
        new_src = resolve_hit_source_text_from_settings(
            dict(src),
            settings=settings,
            embedding_backend=embedding_backend,
            root=root,
        )
        nh = dict(h)
        nh["source"] = new_src
        out.append(nh)
    return out
