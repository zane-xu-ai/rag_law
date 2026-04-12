"""切分预览 HTTP API 与静态页。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from chunking.env_overlap import effective_boundary_overlap_params
from chunking.split import TextChunk, iter_chunks_for_text
from conf.settings import get_settings
from chunking.webui.preview_logic import (
    MAX_PREVIEW_BYTES,
    adjacent_overlaps,
    pick_display_indices,
    section_for_display_index,
    source_paragraph_count,
)

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_doc_seg_pipeline_lock = threading.Lock()
_doc_seg_pipelines: dict[str, Any] = {}


def clear_document_segmentation_pipeline_cache() -> None:
    """测试或热切换模型目录时清空缓存。"""
    with _doc_seg_pipeline_lock:
        _doc_seg_pipelines.clear()


def _get_or_build_document_segmentation_pipeline(model_dir: Path) -> Any:
    """按模型目录缓存 pipeline；首次加载可能较慢。"""
    key = str(model_dir.expanduser().resolve())
    with _doc_seg_pipeline_lock:
        if key not in _doc_seg_pipelines:
            from chunking.document_segmentation import build_document_segmentation_pipeline

            _doc_seg_pipelines[key] = build_document_segmentation_pipeline(key)
        return _doc_seg_pipelines[key]


class PreviewJSONBody(BaseModel):
    text: str = ""
    chunk_size: int = Field(..., ge=1)
    chunk_overlap: int = Field(..., ge=0)
    boundary_aware: bool = False
    compare_semantic: bool = Field(
        default=False,
        description="为 True 时返回句边界切分与句边界+语义合并两套结果，便于对比",
    )
    semantic_merge_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="语义合并相似度阈值；未传则使用服务器配置",
    )
    semantic_merge_min_chars: int | None = Field(
        default=None,
        ge=1,
        description="语义合并最短块优先合并阈值；未传则使用服务器配置",
    )
    semantic_merge_max_chars: int | None = Field(
        default=None,
        ge=1,
        description="语义合并后最大块长；未传则使用服务器配置",
    )


class DocumentSegmentationPreviewBody(BaseModel):
    """与 ``scripts/d04_document_segmentation_export.py`` 相同的方案 D 预览参数。"""

    text: str = ""
    model_path: str | None = Field(
        default=None,
        description="document-segmentation 模型目录；空则使用 DOCUMENT_SEGMENTATION_PATH",
    )
    min_chars: int | None = Field(
        default=None,
        ge=0,
        description="合并过短段阈值；空则读 DOC_SEGMENTATION_MIN_CHARS",
    )
    max_chars: int | None = Field(
        default=None,
        ge=1,
        description="超长再切上限；空则读 DOC_SEGMENTATION_MAX_CHARS",
    )
    split_overlap: int | None = Field(
        default=None,
        ge=0,
        description="超长再切重叠；空则读 DOC_SEGMENTATION_SPLIT_OVERLAP",
    )


def _validate_overlap(size: int, overlap: int) -> None:
    if overlap >= size:
        raise HTTPException(
            status_code=422,
            detail="chunk_overlap 必须小于 chunk_size",
        )


def _check_utf8_size(text: str) -> None:
    raw = text.encode("utf-8")
    if len(raw) > MAX_PREVIEW_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"正文超过上限 {MAX_PREVIEW_BYTES} 字节（UTF-8 编码后长度 {len(raw)}）",
        )


def _boundary_overlap_params(
    chunk_size: int,
    chunk_overlap: int,
    boundary_aware: bool,
) -> tuple[int | None, int | None, bool | None]:
    """句边界模式下的重叠夹紧区间（与 ingest / split 使用 ``effective_boundary_overlap_params`` 一致）。"""
    if not boundary_aware:
        return None, None, None
    st = get_settings()
    f, c, b = effective_boundary_overlap_params(chunk_size, chunk_overlap, st)
    return f, c, b


def _resolve_semantic_merge_nums(
    threshold: float | None,
    min_chars: int | None,
    max_chars: int | None,
) -> tuple[float, int, int]:
    st = get_settings()
    t = st.chunk_semantic_merge_threshold if threshold is None else threshold
    lo = st.chunk_semantic_merge_min_chars if min_chars is None else min_chars
    hi = st.chunk_semantic_merge_max_chars if max_chars is None else max_chars
    return t, lo, hi


def _build_preview_payload(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    *,
    boundary_aware: bool,
    semantic_merge_enabled: bool,
    semantic_merge_threshold: float,
    semantic_merge_min_chars: int,
    semantic_merge_max_chars: int,
) -> dict:
    overlap_floor, overlap_ceiling, boundary_priority_overlap = _boundary_overlap_params(
        chunk_size, chunk_overlap, boundary_aware
    )
    chunks: list[TextChunk] = list(
        iter_chunks_for_text(
            text,
            source_file="preview.txt",
            source_path="preview/preview.txt",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            boundary_aware=boundary_aware,
            overlap_floor=overlap_floor,
            overlap_ceiling=overlap_ceiling,
            boundary_priority_overlap=boundary_priority_overlap,
            semantic_merge_enabled=semantic_merge_enabled,
            semantic_merge_threshold=semantic_merge_threshold,
            semantic_merge_min_chars=semantic_merge_min_chars,
            semantic_merge_max_chars=semantic_merge_max_chars,
        )
    )
    n = len(chunks)
    ranges = [(c.char_start, c.char_end) for c in chunks]
    overlaps = adjacent_overlaps(ranges)
    lengths = [len(c.text) for c in chunks]

    def agg(nums: list[int]) -> dict | None:
        if not nums:
            return None
        return {"min": min(nums), "max": max(nums), "avg": round(sum(nums) / len(nums), 2)}

    summary: dict = {
        "total_chars": len(text),
        "chunk_count": n,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "boundary_aware": boundary_aware,
        "chars_per_chunk": lengths,
        "chars_per_chunk_stats": agg(lengths),
        "overlap_between_adjacent": overlaps,
        "overlap_adjacent_stats": agg(overlaps) if overlaps else None,
        "source_paragraphs": source_paragraph_count(text),
    }
    if boundary_aware:
        summary["overlap_floor_effective"] = overlap_floor
        summary["overlap_ceiling_effective"] = overlap_ceiling
        summary["boundary_priority_overlap_effective"] = boundary_priority_overlap
        summary["boundary_length_note"] = (
            "句边界对齐：chunk_size 是滑窗初值长度上限，不是「每块必须写满」的下限。"
            "对齐后实际块长多为 ≤chunk_size：句首/句尾会就近移到句界或弱标点（±max_probe），"
            "重叠区间还会夹紧起点，二者都常使块变短。"
            "理论上单块最长约 chunk_size+2*max_probe（首尾同时向外对齐），实践中罕见；"
            "末块不足 chunk_size 也属正常。"
        )

    summary["semantic_merge_enabled"] = semantic_merge_enabled
    summary["semantic_merge_threshold"] = semantic_merge_threshold
    summary["semantic_merge_min_chars"] = semantic_merge_min_chars
    summary["semantic_merge_max_chars"] = semantic_merge_max_chars
    if semantic_merge_enabled:
        summary["semantic_merge_note"] = (
            "语义合并：在句边界（或滑窗）切分结果上，对相邻块用字符 2-gram 余弦相似度判断；"
            "当上一块长度 < min_chars、合并后长度 ≤ max_chars 且相似度 ≥ threshold 时合并为一块。"
        )

    if n == 0:
        display = {
            "mode": "full",
            "total_chunks": 0,
            "omitted_message": None,
            "chunks": [],
        }
        return {"summary": summary, "display": display}

    mode = "full" if n <= 15 else "truncated"
    indices = pick_display_indices(n)
    display_chunks: list[dict] = []
    for i in indices:
        c = chunks[i]
        overlap_prev = overlaps[i - 1] if i > 0 else 0
        overlap_next = overlaps[i] if i < n - 1 else 0
        display_chunks.append(
            {
                "index": c.chunk_index,
                "text": c.text,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "section": section_for_display_index(i, n),
                "overlap_prev": overlap_prev,
                "overlap_next": overlap_next,
            }
        )

    omitted_message: str | None = None
    if mode == "truncated":
        omitted_message = (
            f"共 {n} 段，仅展示前 5、中间 5、后 5 段（共 15 段），其余已省略。"
        )

    display = {
        "mode": mode,
        "total_chunks": n,
        "omitted_message": omitted_message,
        "chunks": display_chunks,
    }
    return {"summary": summary, "display": display}


def _run_preview(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    *,
    boundary_aware: bool = False,
    compare_semantic: bool = False,
    semantic_merge_threshold: float | None = None,
    semantic_merge_min_chars: int | None = None,
    semantic_merge_max_chars: int | None = None,
) -> dict:
    if chunk_size < 1:
        raise HTTPException(status_code=422, detail="chunk_size 至少为 1")
    _validate_overlap(chunk_size, chunk_overlap)
    _check_utf8_size(text)

    st_thr, st_min, st_max = _resolve_semantic_merge_nums(
        semantic_merge_threshold,
        semantic_merge_min_chars,
        semantic_merge_max_chars,
    )

    if compare_semantic:
        boundary_payload = _build_preview_payload(
            text,
            chunk_size,
            chunk_overlap,
            boundary_aware=boundary_aware,
            semantic_merge_enabled=False,
            semantic_merge_threshold=st_thr,
            semantic_merge_min_chars=st_min,
            semantic_merge_max_chars=st_max,
        )
        merged_payload = _build_preview_payload(
            text,
            chunk_size,
            chunk_overlap,
            boundary_aware=boundary_aware,
            semantic_merge_enabled=True,
            semantic_merge_threshold=st_thr,
            semantic_merge_min_chars=st_min,
            semantic_merge_max_chars=st_max,
        )
        return {
            "mode": "comparison",
            "boundary": boundary_payload,
            "semantic_merged": merged_payload,
        }

    single = _build_preview_payload(
        text,
        chunk_size,
        chunk_overlap,
        boundary_aware=boundary_aware,
        semantic_merge_enabled=False,
        semantic_merge_threshold=st_thr,
        semantic_merge_min_chars=st_min,
        semantic_merge_max_chars=st_max,
    )
    return {
        "mode": "single",
        "summary": single["summary"],
        "display": single["display"],
    }


def _agg_ints(nums: list[int]) -> dict | None:
    if not nums:
        return None
    return {"min": min(nums), "max": max(nums), "avg": round(sum(nums) / len(nums), 2)}


def _chunks_to_single_preview(text: str, chunks: list[TextChunk], *, summary: dict) -> dict:
    """由已切好的 ``TextChunk`` 列表生成与滑窗预览相同外形的 ``summary`` + ``display``。"""
    n = len(chunks)
    ranges = [(c.char_start, c.char_end) for c in chunks]
    overlaps = adjacent_overlaps(ranges)
    lengths = [len(c.text) for c in chunks]
    summary_out = {
        **summary,
        "total_chars": len(text),
        "chunk_count": n,
        "chars_per_chunk": lengths,
        "chars_per_chunk_stats": _agg_ints(lengths),
        "overlap_between_adjacent": overlaps,
        "overlap_adjacent_stats": _agg_ints(overlaps) if overlaps else None,
        "source_paragraphs": source_paragraph_count(text),
    }

    if n == 0:
        display = {
            "mode": "full",
            "total_chunks": 0,
            "omitted_message": None,
            "chunks": [],
        }
        return {"mode": "single", "summary": summary_out, "display": display}

    mode = "full" if n <= 15 else "truncated"
    indices = pick_display_indices(n)
    display_chunks: list[dict] = []
    for i in indices:
        c = chunks[i]
        overlap_prev = overlaps[i - 1] if i > 0 else 0
        overlap_next = overlaps[i] if i < n - 1 else 0
        display_chunks.append(
            {
                "index": c.chunk_index,
                "text": c.text,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "section": section_for_display_index(i, n),
                "overlap_prev": overlap_prev,
                "overlap_next": overlap_next,
            }
        )

    omitted_message: str | None = None
    if mode == "truncated":
        omitted_message = (
            f"共 {n} 段，仅展示前 5、中间 5、后 5 段（共 15 段），其余已省略。"
        )

    display = {
        "mode": mode,
        "total_chunks": n,
        "omitted_message": omitted_message,
        "chunks": display_chunks,
    }
    return {"mode": "single", "summary": summary_out, "display": display}


def _resolve_model_dir_for_doc_seg(model_path: str | None) -> Path:
    st = get_settings()
    raw = (model_path or "").strip() or (st.document_segmentation_path or "")
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="未配置模型目录：请在请求中传 model_path，或在 .env 设置 DOCUMENT_SEGMENTATION_PATH",
        )
    mp = Path(raw).expanduser().resolve()
    if not mp.is_dir():
        raise HTTPException(status_code=400, detail=f"模型目录不存在: {mp}")
    return mp


def _resolve_doc_seg_ints(
    min_chars: int | None,
    max_chars: int | None,
    split_overlap: int | None,
) -> tuple[int, int, int]:
    st = get_settings()
    mc = st.doc_segmentation_min_chars if min_chars is None else min_chars
    mx = st.doc_segmentation_max_chars if max_chars is None else max_chars
    ov = st.doc_segmentation_split_overlap if split_overlap is None else split_overlap
    return mc, mx, ov


def _run_document_segmentation_preview_sync(
    text: str,
    model_dir: Path,
    min_chars: int,
    max_chars: int,
    split_overlap: int,
) -> dict:
    from chunking.document_segmentation import (
        infer_raw_ranges_from_pipeline,
        iter_document_segmentation_chunks_for_text,
    )

    pipe = _get_or_build_document_segmentation_pipeline(model_dir)
    chunks = list(
        iter_document_segmentation_chunks_for_text(
            text,
            source_file="preview.txt",
            source_path="preview/preview.txt",
            raw_ranges_fn=lambda t, _p=pipe: infer_raw_ranges_from_pipeline(t, _p),
            min_chars=min_chars,
            max_chars=max_chars,
            split_overlap=split_overlap,
        )
    )
    summary = {
        "method": "document_segmentation_d",
        "model_dir": str(model_dir),
        "doc_segmentation_min_chars": min_chars,
        "doc_segmentation_max_chars": max_chars,
        "doc_segmentation_split_overlap": split_overlap,
        "doc_segmentation_note": (
            "方案 D：ModelScope document-segmentation 得到语义段，再经 min/max 与换行优先再切分；"
            "与滑窗的 chunk_size/overlap 无关。"
        ),
    }
    return _chunks_to_single_preview(text, chunks, summary=summary)


app = FastAPI(title="rag-law chunk preview", version="0.1.0")


@app.post("/api/preview")
async def api_preview(request: Request) -> JSONResponse:
    ct = request.headers.get("content-type", "")

    if "application/json" in ct:
        body = PreviewJSONBody.model_validate(await request.json())
        text = body.text
        return JSONResponse(
            _run_preview(
                text,
                body.chunk_size,
                body.chunk_overlap,
                boundary_aware=body.boundary_aware,
                compare_semantic=body.compare_semantic,
                semantic_merge_threshold=body.semantic_merge_threshold,
                semantic_merge_min_chars=body.semantic_merge_min_chars,
                semantic_merge_max_chars=body.semantic_merge_max_chars,
            )
        )

    if "multipart/form-data" in ct:
        form = await request.form()
        raw_text = form.get("text")
        text = raw_text if isinstance(raw_text, str) else ""
        up = form.get("file")
        if (not text or not text.strip()) and up is not None:
            if hasattr(up, "read"):
                data = await up.read()
                if len(data) > MAX_PREVIEW_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"上传文件超过上限 {MAX_PREVIEW_BYTES} 字节",
                    )
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件须为 UTF-8 文本：{e}",
                    ) from e
        try:
            chunk_size = int(form.get("chunk_size", "0"))
            chunk_overlap = int(form.get("chunk_overlap", "0"))
        except (TypeError, ValueError) as e:
            raise HTTPException(status_code=422, detail="chunk_size / chunk_overlap 须为整数") from e
        ba_raw = form.get("boundary_aware")
        boundary_aware = ba_raw in ("true", "1", "on", True)
        cs_raw = form.get("compare_semantic")
        compare_semantic = cs_raw in ("true", "1", "on", True)

        def _opt_float(key: str) -> float | None:
            v = form.get(key)
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (TypeError, ValueError) as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"{key} 须为数字",
                ) from e

        def _opt_int(key: str) -> int | None:
            v = form.get(key)
            if v is None or v == "":
                return None
            try:
                return int(v)
            except (TypeError, ValueError) as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"{key} 须为整数",
                ) from e

        return JSONResponse(
            _run_preview(
                text,
                chunk_size,
                chunk_overlap,
                boundary_aware=boundary_aware,
                compare_semantic=compare_semantic,
                semantic_merge_threshold=_opt_float("semantic_merge_threshold"),
                semantic_merge_min_chars=_opt_int("semantic_merge_min_chars"),
                semantic_merge_max_chars=_opt_int("semantic_merge_max_chars"),
            )
        )

    raise HTTPException(
        status_code=415,
        detail="Content-Type 须为 application/json 或 multipart/form-data",
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/document-segmentation/status")
def document_segmentation_status() -> dict[str, Any]:
    """方案 D：模型路径与 modelscope 是否可 import（不加载权重）。"""
    st = get_settings()
    p = st.document_segmentation_path
    import_ok = False
    try:
        import modelscope.pipelines  # noqa: F401

        import_ok = True
    except ImportError:
        pass
    return {
        "document_segmentation_path": p,
        "path_exists": bool(p and Path(p).expanduser().is_dir()),
        "modelscope_import_ok": import_ok,
    }


@app.post("/api/preview-document-segmentation")
async def api_preview_document_segmentation(request: Request) -> JSONResponse:
    """方案 D 文档分段模型预览（与 ``d04_document_segmentation_export`` 同源逻辑）。"""
    ct = request.headers.get("content-type", "")

    if "application/json" in ct:
        body = DocumentSegmentationPreviewBody.model_validate(await request.json())
        text = body.text
        model_path = body.model_path
        min_c, max_c, ov = _resolve_doc_seg_ints(
            body.min_chars, body.max_chars, body.split_overlap
        )
    elif "multipart/form-data" in ct:
        form = await request.form()
        raw_text = form.get("text")
        text = raw_text if isinstance(raw_text, str) else ""
        up = form.get("file")
        if (not text or not text.strip()) and up is not None:
            if hasattr(up, "read"):
                data = await up.read()
                if len(data) > MAX_PREVIEW_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"上传文件超过上限 {MAX_PREVIEW_BYTES} 字节",
                    )
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件须为 UTF-8 文本：{e}",
                    ) from e
        mp_raw = form.get("model_path")
        model_path = mp_raw if isinstance(mp_raw, str) else None

        def _form_int(name: str) -> int | None:
            v = form.get(name)
            if v is None or v == "":
                return None
            try:
                return int(v)
            except (TypeError, ValueError) as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"{name} 须为整数",
                ) from e

        min_c, max_c, ov = _resolve_doc_seg_ints(
            _form_int("min_chars"),
            _form_int("max_chars"),
            _form_int("split_overlap"),
        )
    else:
        raise HTTPException(
            status_code=415,
            detail="Content-Type 须为 application/json 或 multipart/form-data",
        )

    _check_utf8_size(text)
    if ov >= max_c:
        raise HTTPException(
            status_code=422,
            detail="split_overlap 须小于 max_chars",
        )
    model_dir = _resolve_model_dir_for_doc_seg(model_path)

    try:
        payload = await run_in_threadpool(
            _run_document_segmentation_preview_sync,
            text,
            model_dir,
            min_c,
            max_c,
            ov,
        )
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail="无法加载 modelscope（请 uv sync --extra segmentation）：%s" % (e,),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="文档分段推理失败：%s" % (e,),
        ) from e

    return JSONResponse(payload)


# 静态资源：在注册 API 之后挂载，避免覆盖 /api
if _STATIC_DIR.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_STATIC_DIR), html=True),
        name="static",
    )
