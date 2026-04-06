"""切分预览 HTTP API 与静态页。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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


class PreviewJSONBody(BaseModel):
    text: str = ""
    chunk_size: int = Field(..., ge=1)
    chunk_overlap: int = Field(..., ge=0)
    boundary_aware: bool = False


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


def _run_preview(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    *,
    boundary_aware: bool = False,
) -> dict:
    if chunk_size < 1:
        raise HTTPException(status_code=422, detail="chunk_size 至少为 1")
    _validate_overlap(chunk_size, chunk_overlap)
    _check_utf8_size(text)

    # 预览请求的 chunk_overlap 可与 .env 中全局值不同；重叠下/上界不得超过本次请求的 chunk_overlap
    overlap_floor = None
    overlap_ceiling = None
    if boundary_aware:
        st = get_settings()
        overlap_floor = min(chunk_overlap, st.chunk_overlap_floor)
        overlap_ceiling = min(chunk_overlap, st.chunk_overlap_ceiling)
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
        summary["boundary_length_note"] = (
            "句边界对齐：chunk_size 是滑窗初值长度上限，不是「每块必须写满」的下限。"
            "对齐后实际块长多为 ≤chunk_size：句首/句尾会就近移到句界或弱标点（±max_probe），"
            "重叠区间还会夹紧起点，二者都常使块变短。"
            "理论上单块最长约 chunk_size+2*max_probe（首尾同时向外对齐），实践中罕见；"
            "末块不足 chunk_size 也属正常。"
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
        display_chunks.append(
            {
                "index": c.chunk_index,
                "text": c.text,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "section": section_for_display_index(i, n),
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
        return JSONResponse(
            _run_preview(
                text,
                chunk_size,
                chunk_overlap,
                boundary_aware=boundary_aware,
            )
        )

    raise HTTPException(
        status_code=415,
        detail="Content-Type 须为 application/json 或 multipart/form-data",
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# 静态资源：在注册 API 之后挂载，避免覆盖 /api
if _STATIC_DIR.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_STATIC_DIR), html=True),
        name="static",
    )
