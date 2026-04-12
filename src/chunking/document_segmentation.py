"""方案 D：文档分段模型（ModelScope document-segmentation 等）→ 与方案 C 一致的 min/max 块长后处理。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from chunking.boundary import is_acceptable_tail
from chunking.breakpoint_embed import _merge_ranges_min_len
from chunking.split import TextChunk
from conf.settings import project_root


def default_document_segmentation_separator() -> str:
    """块与块之间分隔条（与方案 C 的 ``default_chunk_separator`` 区分，便于 diff）。"""
    bar = "#" * 88
    return (
        "\n\n"
        + bar
        + "\n"
        + "##>>> CHUNK_BOUNDARY (document_segmentation D) <<<##\n"
        + bar
        + "\n\n"
    )


def split_document_segmentation_export_to_chunks(export_text: str, *, separator: str | None = None) -> list[str]:
    sep = separator if separator is not None else default_document_segmentation_separator()
    return export_text.split(sep)


def _segment_match_prefixes(seg: str) -> list[str]:
    """用于在原文中定位下一段起点：模型输出常见带 ``\\t`` / 与 MinerU 源文不一致的空白。"""
    seen: set[str] = set()
    out: list[str] = []
    for c in (
        seg,
        seg.replace("\t", ""),
        seg.replace("\t", " "),
        seg.lstrip(" \t\n\r"),
        seg.lstrip(" \t\n\r").replace("\t", ""),
    ):
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _find_next_segment_start(full_text: str, next_seg: str, cursor: int) -> int:
    """从 ``cursor`` 起在原文中定位 ``next_seg`` 的最早出现（多前缀变体取最小下标）。"""
    best: int | None = None
    for v in _segment_match_prefixes(next_seg):
        i = full_text.find(v, cursor)
        if i >= 0 and (best is None or i < best):
            best = i
    if best is None:
        raise ValueError(
            "无法在原文中找到下一分段的起始（cursor=%s, 下一片段前缀=%r）"
            % (cursor, next_seg[:120])
        )
    return best


def segments_to_char_ranges(full_text: str, segments: list[str]) -> list[tuple[int, int]]:
    """将模型返回的片段列表映射为原文中的 ``[start, end)`` 区间（顺序、无间隙、划分全文）。

    1. 若 ``"".join(segments) == full_text``：按片段长度顺排（逐字与原文一致）。
    2. 否则：用「下一片段在原文中的起始位置」划分（容忍制表符等差异，与 ModelScope / MinerU 常见不一致对齐）。
    """
    if not full_text:
        return []
    if not segments:
        return [(0, len(full_text))]
    joined = "".join(segments)
    if joined == full_text:
        pos = 0
        out: list[tuple[int, int]] = []
        for s in segments:
            L = len(s)
            out.append((pos, pos + L))
            pos += L
        return out

    segs = [s for s in segments if s != ""]
    if not segs:
        return [(0, len(full_text))]
    if len(segs) == 1:
        return [(0, len(full_text))]

    ranges: list[tuple[int, int]] = []
    cursor = 0
    for k in range(len(segs) - 1):
        start_next = _find_next_segment_start(full_text, segs[k + 1], cursor)
        if start_next < cursor:
            raise ValueError(
                "分段边界回退（cursor=%s, start_next=%s）" % (cursor, start_next)
            )
        ranges.append((cursor, start_next))
        cursor = start_next
    ranges.append((cursor, len(full_text)))
    return ranges


def _coerce_segments_from_pipeline_output(out: Any) -> list[str] | None:
    if out is None:
        return None
    if isinstance(out, str):
        return [out]
    if isinstance(out, list):
        if all(isinstance(x, str) for x in out):
            return out
        if out and all(isinstance(x, dict) for x in out):
            texts: list[str] = []
            for x in out:
                t = x.get("text") or x.get("sentence") or x.get("content")
                if t is not None:
                    texts.append(str(t))
            return texts or None
    if isinstance(out, dict):
        for k in ("segments", "output", "texts", "sentences", "result"):
            v = out.get(k)
            if isinstance(v, list) and v and isinstance(v[0], str):
                return v
        t0 = out.get("text")
        if isinstance(t0, str):
            return [t0]
    return None


def _call_document_segmentation_pipeline(pipeline: Any, full_text: str) -> Any:
    try:
        return pipeline(full_text)
    except Exception:
        pass
    for key in ("text", "src", "input"):
        try:
            return pipeline({key: full_text})
        except Exception:
            continue
    return pipeline(full_text)


def _split_range_max_len_document_d(
    full_text: str,
    s: int,
    e: int,
    max_chars: int,
    overlap: int,
) -> list[tuple[int, int]]:
    """单段 ``[s,e)`` 超过 ``max_chars`` 时再切分。

    MinerU 法规 md 多为短行 + 换行；纯 ``iter_text_slices`` 会在「（二）/（三）」、
    「作/出」等换行两侧硬截断。此处 ``overlap==0`` 时在窗口内**优先**在最后一个换行处断开，
    否则退回 ``is_acceptable_tail``；``overlap>0`` 时用 ``iter_text_slices_boundary_aware``。
    """
    piece = full_text[s:e]
    n = len(piece)
    if n <= max_chars:
        return [(s, e)]
    if overlap >= max_chars:
        raise ValueError("split_overlap 必须小于 max_chars")

    if overlap > 0:
        from chunking.boundary import (
            DEFAULT_MAX_PROBE,
            _effective_max_boundary_scan,
            iter_text_slices_boundary_aware,
        )

        scan = _effective_max_boundary_scan(max_chars, DEFAULT_MAX_PROBE, None)
        out: list[tuple[int, int]] = []
        for _seg, rel0, rel1 in iter_text_slices_boundary_aware(
            piece,
            max_chars,
            overlap,
            overlap_floor=overlap,
            overlap_ceiling=overlap,
            max_boundary_scan=scan,
        ):
            out.append((s + rel0, s + rel1))
        return out

    max_scan = min(800, max_chars)
    out2: list[tuple[int, int]] = []
    cursor = 0
    while cursor < n:
        rest = n - cursor
        if rest <= max_chars:
            out2.append((s + cursor, s + n))
            break
        hard_hi = min(cursor + max_chars, n)
        lo = max(cursor + 1, hard_hi - max_scan)
        end = hard_hi
        found_nl = False
        for i in range(hard_hi - 1, lo - 1, -1):
            if piece[i] == "\n":
                end = i + 1
                found_nl = True
                break
        if not found_nl:
            for j in range(hard_hi, lo, -1):
                if is_acceptable_tail(piece, j):
                    end = j
                    break
        if end <= cursor:
            end = min(cursor + max_chars, n)
        out2.append((s + cursor, s + end))
        cursor = end
    return out2


def infer_raw_ranges_from_pipeline(full_text: str, pipeline: Any) -> list[tuple[int, int]]:
    """调用 ModelScope 类 ``document-segmentation`` pipeline，得到合并前的语义段区间。"""
    out = _call_document_segmentation_pipeline(pipeline, full_text)
    segments = _coerce_segments_from_pipeline_output(out)
    if not segments:
        return [(0, len(full_text))]
    return segments_to_char_ranges(full_text, segments)


def build_document_segmentation_pipeline(model_path: str | Path) -> Any:
    """加载本地或 Hub 路径下的 document-segmentation 模型（依赖 ``modelscope``）。"""
    import warnings

    warnings.filterwarnings(
        "ignore",
        message="Passing `gradient_checkpointing` to a config initialization is deprecated",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message="The `device` argument is deprecated and will be removed in v5 of Transformers.",
        category=FutureWarning,
    )
    try:
        from modelscope.pipelines import pipeline
    except ImportError as e:
        raise ImportError(
            "方案 D 无法 import modelscope.pipelines（原因：%r）。"
            "请执行：uv sync --extra segmentation（已包含 torch、Pillow、datasets、addict 等传递依赖）。"
            "若已执行仍失败，可再试：uv sync --extra embedding --extra segmentation。"
            % (e,)
        ) from e
    mp = str(Path(model_path).expanduser().resolve())
    return pipeline(task="document-segmentation", model=mp)


def iter_document_segmentation_chunks_for_text(
    full_text: str,
    *,
    source_file: str,
    source_path: str | None,
    raw_ranges_fn: Callable[[str], list[tuple[int, int]]],
    min_chars: int = 0,
    max_chars: int = 1200,
    split_overlap: int = 0,
) -> Iterator[TextChunk]:
    """``raw_ranges_fn`` 由 pipeline 或测试注入：``full_text -> [(s,e), ...]``。

    ``min_chars=0`` 时不做「过短段向前合并」，便于保留文档分段模型的原始边界；
    与方案 C 对齐的公平对比可传 ``min_chars=200``、``max_chars=2200``（由 CLI 显式指定）。
    """
    n = len(full_text)
    if n == 0:
        return
    sid = source_path or source_file
    raw = raw_ranges_fn(full_text)
    if not raw:
        raw = [(0, n)]
    merged = _merge_ranges_min_len(raw, min_chars)
    final_ranges: list[tuple[int, int]] = []
    for s, e in merged:
        final_ranges.extend(
            _split_range_max_len_document_d(full_text, s, e, max_chars, split_overlap)
        )

    for idx, (cs, ce) in enumerate(final_ranges):
        yield TextChunk(
            text=full_text[cs:ce],
            source_file=source_file,
            chunk_index=idx,
            char_start=cs,
            char_end=ce,
            source_path=source_path,
            source_id=sid,
            extra={"chunking": "document_segmentation_d"},
        )


def export_document_segmentation_chunks_dir(
    md_paths: list[Path],
    out_dir: Path,
    pipeline: Any,
    *,
    min_chars: int = 0,
    max_chars: int = 1200,
    split_overlap: int = 0,
    chunk_separator: str | None = None,
    progress: bool = True,
) -> list[Path]:
    """将若干 .md 按方案 D 切分并写入 ``out_dir/<basename>.md``。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sep = chunk_separator if chunk_separator is not None else default_document_segmentation_separator()
    written: list[Path] = []
    root = project_root()
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None  # type: ignore[misc, assignment]
    use_bar = bool(progress and tqdm is not None)
    path_iter = tqdm(md_paths, desc="d04 doc-seg", unit="file") if use_bar else md_paths

    for md in path_iter:
        p = Path(md)
        if use_bar and hasattr(path_iter, "set_postfix_str"):
            path_iter.set_postfix_str(p.name[:48] + ("…" if len(p.name) > 48 else ""))
        text = p.read_text(encoding="utf-8")
        try:
            sp = p.resolve().relative_to(root).as_posix()
        except ValueError:
            sp = p.name
        chunks = list(
            iter_document_segmentation_chunks_for_text(
                text,
                source_file=p.name,
                source_path=sp,
                raw_ranges_fn=lambda t, _pipe=pipeline: infer_raw_ranges_from_pipeline(t, _pipe),
                min_chars=min_chars,
                max_chars=max_chars,
                split_overlap=split_overlap,
            )
        )
        bodies: list[str] = []
        for i, c in enumerate(chunks):
            if i > 0:
                bodies.append(sep)
            bodies.append(c.text)
        dest = out / p.name
        dest.write_text("".join(bodies), encoding="utf-8")
        written.append(dest)
    return written
