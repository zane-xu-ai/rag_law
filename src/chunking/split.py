"""字符滑窗切分：单文本、单文件、`data/*.md` 目录遍历。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from loguru import logger

from conf.settings import get_settings, project_root
from embeddings.base import EmbeddingBackend

from chunking.boundary import (
    DEFAULT_MAX_PROBE,
    _effective_max_boundary_scan,
    iter_text_slices_boundary_aware,
)
from chunking.env_overlap import effective_boundary_overlap_params


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


def _char_ngrams(text: str, n: int = 2) -> Counter[str]:
    s = (text or "").strip()
    if not s:
        return Counter()
    if len(s) < n:
        return Counter({s: 1})
    return Counter(s[i : i + n] for i in range(0, len(s) - n + 1))


def _cosine_sim_counter(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    for k, av in a.items():
        bv = b.get(k)
        if bv:
            dot += float(av * bv)
    if dot <= 0.0:
        return 0.0
    na = sum(float(v * v) for v in a.values()) ** 0.5
    nb = sum(float(v * v) for v in b.values()) ** 0.5
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


def _cosine_dense(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


def _semantic_merge_chunks_char_ngram(
    chunks: list[TextChunk],
    *,
    similarity_threshold: float,
    min_chunk_chars: int,
    max_chunk_chars: int,
) -> tuple[list[TextChunk], dict[str, float]]:
    merged: list[TextChunk] = []
    merge_hits = 0
    merge_checks = 0

    current = chunks[0]
    current_vec = _char_ngrams(current.text)

    for nxt in chunks[1:]:
        cand_len = len(current.text) + len(nxt.text)
        allow_by_len = len(current.text) < min_chunk_chars and cand_len <= max_chunk_chars
        merge_checks += 1
        sim = _cosine_sim_counter(current_vec, _char_ngrams(nxt.text))
        if allow_by_len and sim >= similarity_threshold:
            joiner = "" if current.text.endswith(("\n", "。", "！", "？", ";", "；")) else "\n"
            current = TextChunk(
                text=f"{current.text}{joiner}{nxt.text}",
                source_file=current.source_file,
                chunk_index=current.chunk_index,
                char_start=current.char_start,
                char_end=nxt.char_end,
                source_path=current.source_path,
                source_id=current.source_id,
                mime_type=current.mime_type,
                doc_type=current.doc_type,
                domain=current.domain,
                extra=current.extra,
            )
            current_vec = _char_ngrams(current.text)
            merge_hits += 1
            continue
        merged.append(current)
        current = nxt
        current_vec = _char_ngrams(current.text)
    merged.append(current)

    for i, c in enumerate(merged):
        c.chunk_index = i

    hit_rate = (merge_hits / merge_checks) if merge_checks > 0 else 0.0
    stats = {
        "before_count": float(len(chunks)),
        "after_count": float(len(merged)),
        "merge_ratio": float(len(merged)) / float(len(chunks)),
        "merge_hits": float(merge_hits),
        "merge_checks": float(merge_checks),
        "threshold_hit_rate": hit_rate,
    }
    return merged, stats


def _semantic_merge_chunks_embedding(
    chunks: list[TextChunk],
    *,
    similarity_threshold: float,
    min_chunk_chars: int,
    max_chunk_chars: int,
    embedder: EmbeddingBackend,
) -> tuple[list[TextChunk], dict[str, float]]:
    """相邻块合并：用 BGE 等稠密向量余弦相似度（与入库向量一致）。"""
    merged: list[TextChunk] = []
    merge_hits = 0
    merge_checks = 0

    pre = embedder.embed_documents([c.text for c in chunks])
    if len(pre) != len(chunks):
        raise RuntimeError("embed_documents 返回条数与块数不一致")

    current = chunks[0]
    current_e = pre[0]

    for i in range(1, len(chunks)):
        nxt = chunks[i]
        nxt_e = pre[i]
        cand_len = len(current.text) + len(nxt.text)
        allow_by_len = len(current.text) < min_chunk_chars and cand_len <= max_chunk_chars
        merge_checks += 1
        sim = _cosine_dense(current_e, nxt_e)
        if allow_by_len and sim >= similarity_threshold:
            joiner = "" if current.text.endswith(("\n", "。", "！", "？", ";", "；")) else "\n"
            merged_text = f"{current.text}{joiner}{nxt.text}"
            current = TextChunk(
                text=merged_text,
                source_file=current.source_file,
                chunk_index=current.chunk_index,
                char_start=current.char_start,
                char_end=nxt.char_end,
                source_path=current.source_path,
                source_id=current.source_id,
                mime_type=current.mime_type,
                doc_type=current.doc_type,
                domain=current.domain,
                extra=current.extra,
            )
            current_e = embedder.embed_documents([merged_text])[0]
            merge_hits += 1
        else:
            merged.append(current)
            current = nxt
            current_e = nxt_e

    merged.append(current)

    for j, c in enumerate(merged):
        c.chunk_index = j

    hit_rate = (merge_hits / merge_checks) if merge_checks > 0 else 0.0
    stats = {
        "before_count": float(len(chunks)),
        "after_count": float(len(merged)),
        "merge_ratio": float(len(merged)) / float(len(chunks)),
        "merge_hits": float(merge_hits),
        "merge_checks": float(merge_checks),
        "threshold_hit_rate": hit_rate,
    }
    return merged, stats


def semantic_merge_chunks(
    chunks: list[TextChunk],
    *,
    similarity_threshold: float,
    min_chunk_chars: int,
    max_chunk_chars: int,
    similarity_backend: Literal["char_ngram", "embedding"] = "char_ngram",
    embedder: EmbeddingBackend | None = None,
) -> tuple[list[TextChunk], dict[str, float]]:
    """相邻块语义动态合并：char_ngram（2-gram 余弦）或 embedding（BGE 余弦）。"""
    if not chunks:
        return [], {
            "before_count": 0.0,
            "after_count": 0.0,
            "merge_ratio": 0.0,
            "merge_hits": 0.0,
            "merge_checks": 0.0,
            "threshold_hit_rate": 0.0,
        }
    if similarity_backend == "embedding":
        if embedder is None:
            raise ValueError(
                "semantic_merge 使用 embedding 时须传入 embedder（例如 embeddings.build_embedder(settings)）",
            )
        return _semantic_merge_chunks_embedding(
            chunks,
            similarity_threshold=similarity_threshold,
            min_chunk_chars=min_chunk_chars,
            max_chunk_chars=max_chunk_chars,
            embedder=embedder,
        )
    return _semantic_merge_chunks_char_ngram(
        chunks,
        similarity_threshold=similarity_threshold,
        min_chunk_chars=min_chunk_chars,
        max_chunk_chars=max_chunk_chars,
    )


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
    overlap_floor: Optional[int] = None,
    overlap_ceiling: Optional[int] = None,
    max_boundary_scan: Optional[int] = None,
    boundary_priority_overlap: Optional[bool] = None,
    clamp_adjust_max_rounds: Optional[int] = None,
    semantic_merge_enabled: bool = False,
    semantic_merge_similarity: Literal["char_ngram", "embedding"] = "char_ngram",
    embedding_backend: EmbeddingBackend | None = None,
    semantic_merge_threshold: float = 0.82,
    semantic_merge_min_chars: int = 220,
    semantic_merge_max_chars: int = 2200,
) -> Iterator[TextChunk]:
    """对已有字符串切分并附加元数据（单文件内 chunk_index 从 0 递增）。

    `boundary_aware=True` 时在滑窗初值上按句界（强→弱→初值）微调首尾，见 `doc/chunk/句边界对齐切分.md`。
    重叠下界/上界未传时均等于 `chunk_overlap`；批量与预览可从 `get_settings()` 传入。
    """
    sid = source_path or source_file
    if boundary_aware:
        floor = overlap_floor if overlap_floor is not None else chunk_overlap
        ceiling = overlap_ceiling if overlap_ceiling is not None else chunk_overlap
        scan = _effective_max_boundary_scan(chunk_size, DEFAULT_MAX_PROBE, max_boundary_scan)
        bpo = False if boundary_priority_overlap is None else boundary_priority_overlap
        car = 2 if clamp_adjust_max_rounds is None else clamp_adjust_max_rounds
        slicer_iter = iter_text_slices_boundary_aware(
            full_text,
            chunk_size,
            chunk_overlap,
            overlap_floor=floor,
            overlap_ceiling=ceiling,
            max_boundary_scan=scan,
            boundary_priority_overlap=bpo,
            clamp_adjust_max_rounds=car,
        )
    else:
        slicer_iter = iter_text_slices(full_text, chunk_size, chunk_overlap)
    chunks: list[TextChunk] = []
    for idx, (piece, c0, c1) in enumerate(slicer_iter):
        chunks.append(
            TextChunk(
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
        )
    if semantic_merge_enabled and chunks:
        if semantic_merge_similarity == "embedding" and embedding_backend is None:
            raise ValueError(
                "semantic_merge_similarity=embedding 时须提供 embedding_backend（如 ingest 中 build_embedder）",
            )
        before = len(chunks)
        chunks, stats = semantic_merge_chunks(
            chunks,
            similarity_threshold=semantic_merge_threshold,
            min_chunk_chars=semantic_merge_min_chars,
            max_chunk_chars=semantic_merge_max_chars,
            similarity_backend=semantic_merge_similarity,
            embedder=embedding_backend,
        )
        logger.bind(
            event="chunk_semantic_merge",
            source_file=source_file,
            similarity_backend=semantic_merge_similarity,
            before_count=before,
            after_count=len(chunks),
            merge_ratio=stats["merge_ratio"],
            threshold_hit_rate=stats["threshold_hit_rate"],
        ).info("chunk_semantic_merge_done")
    for c in chunks:
        yield c


def iter_file_chunks(
    md_path: Path,
    *,
    chunk_size: int,
    chunk_overlap: int,
    root: Optional[Path] = None,
    boundary_aware: bool = False,
    overlap_floor: Optional[int] = None,
    overlap_ceiling: Optional[int] = None,
    max_boundary_scan: Optional[int] = None,
    boundary_priority_overlap: Optional[bool] = None,
    clamp_adjust_max_rounds: Optional[int] = None,
    semantic_merge_enabled: bool = False,
    semantic_merge_similarity: Literal["char_ngram", "embedding"] = "char_ngram",
    embedding_backend: EmbeddingBackend | None = None,
    semantic_merge_threshold: float = 0.82,
    semantic_merge_min_chars: int = 220,
    semantic_merge_max_chars: int = 2200,
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
        overlap_floor=overlap_floor,
        overlap_ceiling=overlap_ceiling,
        max_boundary_scan=max_boundary_scan,
        boundary_priority_overlap=boundary_priority_overlap,
        clamp_adjust_max_rounds=clamp_adjust_max_rounds,
        semantic_merge_enabled=semantic_merge_enabled,
        semantic_merge_similarity=semantic_merge_similarity,
        embedding_backend=embedding_backend,
        semantic_merge_threshold=semantic_merge_threshold,
        semantic_merge_min_chars=semantic_merge_min_chars,
        semantic_merge_max_chars=semantic_merge_max_chars,
    )


def iter_chunks_for_data_dir(
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
    semantic_merge_similarity: Literal["char_ngram", "embedding"] | None = None,
    embedding_backend: EmbeddingBackend | None = None,
    semantic_merge_threshold: float = 0.82,
    semantic_merge_min_chars: int = 220,
    semantic_merge_max_chars: int = 2200,
) -> Iterator[TextChunk]:
    """
    遍历目录下所有 `*.md`（排序稳定），依次切分。

    若 `chunk_size` / `chunk_overlap` 未同时显式传入，则从 `conf.get_settings()` 读取缺失项。
    若任一为 None，则两者均从配置读取（避免与 settings 不一致）。
    """
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
    if semantic_merge_similarity is not None:
        eff_sem_sim = semantic_merge_similarity
    elif s is not None:
        eff_sem_sim = s.chunk_semantic_merge_similarity
    else:
        # 与未引入本字段前一致：显式 chunk_size/overlap 且未传 merge 相关参数时不强制读 Settings（便于单测）
        eff_sem_sim = "char_ngram"
    eff_embed = embedding_backend
    if boundary_aware:
        if s is None:
            s = get_settings()
        if overlap_floor is None and overlap_ceiling is None:
            overlap_floor, overlap_ceiling, computed_bpo = effective_boundary_overlap_params(
                chunk_size, chunk_overlap, s
            )
            if eff_bpo is None:
                eff_bpo = computed_bpo
        else:
            if overlap_floor is None:
                overlap_floor = s.chunk_overlap_floor
            if overlap_ceiling is None:
                overlap_ceiling = s.chunk_overlap_ceiling
            if eff_bpo is None:
                eff_bpo = s.chunk_boundary_priority_overlap
        if eff_mb is None:
            eff_mb = s.chunk_boundary_max_scan
        if eff_car is None:
            eff_car = s.chunk_boundary_clamp_adjust_max_rounds

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
            overlap_floor=overlap_floor,
            overlap_ceiling=overlap_ceiling,
            max_boundary_scan=eff_mb,
            boundary_priority_overlap=eff_bpo,
            clamp_adjust_max_rounds=eff_car,
            semantic_merge_enabled=eff_sem_enabled,
            semantic_merge_similarity=eff_sem_sim,
            embedding_backend=eff_embed,
            semantic_merge_threshold=eff_sem_th,
            semantic_merge_min_chars=eff_sem_min,
            semantic_merge_max_chars=eff_sem_max,
        )


def load_all_chunks(
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
    semantic_merge_similarity: Literal["char_ngram", "embedding"] | None = None,
    embedding_backend: EmbeddingBackend | None = None,
    semantic_merge_threshold: float = 0.82,
    semantic_merge_min_chars: int = 220,
    semantic_merge_max_chars: int = 2200,
) -> list[TextChunk]:
    """等价于 `list(iter_chunks_for_data_dir(...))`。"""
    return list(
        iter_chunks_for_data_dir(
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
            semantic_merge_similarity=semantic_merge_similarity,
            embedding_backend=embedding_backend,
            semantic_merge_threshold=semantic_merge_threshold,
            semantic_merge_min_chars=semantic_merge_min_chars,
            semantic_merge_max_chars=semantic_merge_max_chars,
        )
    )
