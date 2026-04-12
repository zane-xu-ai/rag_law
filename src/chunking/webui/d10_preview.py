"""v1.1.10 标题预切分 + 方案 D 预览：供 chunking.webui 与 qa.webui 共用。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from chunking.webui.preview_logic import MAX_PREVIEW_BYTES
from chunking.webui.preview_payload import chunks_to_single_preview


class HeadingPresplitPreviewBody(BaseModel):
    """与 ``scripts/d05_heading_presplit_document_segmentation_export.py`` 对齐的预览请求体。"""

    text: str = ""
    model_path: str | None = Field(default=None, description="覆盖 DOCUMENT_SEGMENTATION_PATH")
    min_chars: int | None = Field(default=None, ge=0)
    max_chars: int | None = Field(default=None, ge=1)
    split_overlap: int | None = Field(default=None, ge=0)
    section_max_chars: int | None = Field(default=None, ge=1, description="空则读 DOC_SEGMENTATION_SECTION_MAX_CHARS 或 max_chars")
    heading_strategy: str | None = Field(
        default=None,
        description="deepest_with_multiple | shallowest_with_multiple | none；空读 CHUNK_MD_HEADING_STRATEGY",
    )
    heading_fixed_level: int | None = Field(default=None, ge=1, le=6)
    heading_single_child: str | None = Field(default=None, description="strict | relaxed")


def _check_utf8_size(text: str) -> None:
    raw = text.encode("utf-8")
    if len(raw) > MAX_PREVIEW_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"正文超过上限 {MAX_PREVIEW_BYTES} 字节（UTF-8 编码后长度 {len(raw)}）",
        )


def chunking_preview_config_dict() -> dict[str, Any]:
    """供 WebUI 默认填充：来自 ``get_settings()`` / ``.env``。"""
    from conf.settings import get_settings

    st = get_settings()
    p = st.document_segmentation_path
    section_max = st.doc_segmentation_section_max_chars or st.doc_segmentation_max_chars
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
        "doc_segmentation_min_chars": st.doc_segmentation_min_chars,
        "doc_segmentation_max_chars": st.doc_segmentation_max_chars,
        "doc_segmentation_split_overlap": st.doc_segmentation_split_overlap,
        "doc_segmentation_section_max_chars": section_max,
        "chunk_md_heading_strategy": st.chunk_md_heading_strategy,
        "chunk_md_heading_fixed_level": st.chunk_md_heading_fixed_level,
        "chunk_md_heading_single_immediate_child": st.chunk_md_heading_single_immediate_child,
    }


def _resolve_model_dir(model_path: str | None) -> Path:
    from conf.settings import get_settings

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
    from conf.settings import get_settings

    st = get_settings()
    mc = st.doc_segmentation_min_chars if min_chars is None else min_chars
    mx = st.doc_segmentation_max_chars if max_chars is None else max_chars
    ov = st.doc_segmentation_split_overlap if split_overlap is None else split_overlap
    return mc, mx, ov


def _resolve_heading_params(
    strategy: str | None,
    fixed_level: int | None,
    single_child: str | None,
    section_max: int | None,
    max_chars: int,
) -> tuple[str, int | None, str, int]:
    from conf.settings import get_settings

    st = get_settings()
    strat = (
        st.chunk_md_heading_strategy if strategy is None else strategy
    ).strip()
    if strat not in ("deepest_with_multiple", "shallowest_with_multiple", "none"):
        strat = "deepest_with_multiple"
    fixed = st.chunk_md_heading_fixed_level if fixed_level is None else fixed_level
    single = (
        st.chunk_md_heading_single_immediate_child
        if single_child is None
        else single_child
    )
    if single not in ("strict", "relaxed"):
        single = "strict"
    sm = (
        st.doc_segmentation_section_max_chars
        if section_max is None
        else section_max
    )
    if sm is None:
        sm = max_chars
    return strat, fixed, single, sm


def run_heading_presplit_document_segmentation_preview_sync(
    text: str,
    model_dir: Path,
    *,
    min_chars: int,
    max_chars: int,
    split_overlap: int,
    section_max_chars: int,
    heading_strategy: str,
    heading_fixed_level: int | None,
    heading_single_child: str,
    get_pipeline: Any,
) -> dict:
    from chunking.md_heading_presplit import (
        iter_heading_presplit_document_segmentation_chunks_for_text,
        leaf_ranges_heading_presplit,
    )

    pipe = get_pipeline(model_dir)
    leaves = leaf_ranges_heading_presplit(
        text,
        strategy=heading_strategy,  # type: ignore[arg-type]
        fixed_first_level=heading_fixed_level,
        single_immediate_child=heading_single_child,  # type: ignore[arg-type]
    )
    chunks = list(
        iter_heading_presplit_document_segmentation_chunks_for_text(
            text,
            source_file="preview.txt",
            source_path="preview/preview.txt",
            pipeline=pipe,
            leaf_ranges=leaves,
            min_chars=min_chars,
            max_chars=max_chars,
            split_overlap=split_overlap,
            section_max_chars=section_max_chars,
        )
    )
    summary = {
        "method": "heading_presplit_d10",
        "model_dir": str(model_dir),
        "doc_segmentation_min_chars": min_chars,
        "doc_segmentation_max_chars": max_chars,
        "doc_segmentation_split_overlap": split_overlap,
        "doc_segmentation_section_max_chars": section_max_chars,
        "chunk_md_heading_strategy": heading_strategy,
        "chunk_md_heading_fixed_level": heading_fixed_level,
        "chunk_md_heading_single_immediate_child": heading_single_child,
        "heading_leaf_count": len(leaves),
        "doc_segmentation_note": (
            "v1.1.10：Markdown ATX 标题递归预切分后，仅超长叶子调用方案 D；"
            "见 doc/plan/v1.1.10-md-heading-presolve-scheme-d.md。"
        ),
    }
    return chunks_to_single_preview(text, chunks, summary=summary)


async def handle_preview_heading_presplit_document_segmentation(
    request: Request,
    *,
    get_pipeline: Any,
) -> dict:
    """解析 JSON 或 multipart，校验后在线程池执行同步预览。"""
    ct = request.headers.get("content-type", "")

    if "application/json" in ct:
        body = HeadingPresplitPreviewBody.model_validate(await request.json())
        text = body.text
        model_path = body.model_path
        min_c, max_c, ov = _resolve_doc_seg_ints(
            body.min_chars, body.max_chars, body.split_overlap
        )
        strat, fixed, single, sec_max = _resolve_heading_params(
            body.heading_strategy,
            body.heading_fixed_level,
            body.heading_single_child,
            body.section_max_chars,
            max_c,
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
        hs = form.get("heading_strategy")
        heading_strategy = hs if isinstance(hs, str) and hs.strip() else None
        hf = form.get("heading_fixed_level")
        heading_fixed_level = _form_int("heading_fixed_level") if hf not in (None, "") else None
        hsc = form.get("heading_single_child")
        heading_single_child = hsc if isinstance(hsc, str) and hsc.strip() else None
        sec_raw = form.get("section_max_chars")
        section_max = _form_int("section_max_chars") if sec_raw not in (None, "") else None
        strat, fixed, single, sec_max = _resolve_heading_params(
            heading_strategy,
            heading_fixed_level,
            heading_single_child,
            section_max,
            max_c,
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
    model_dir = _resolve_model_dir(model_path)

    try:
        return await run_in_threadpool(
            run_heading_presplit_document_segmentation_preview_sync,
            text,
            model_dir,
            min_chars=min_c,
            max_chars=max_c,
            split_overlap=ov,
            section_max_chars=sec_max,
            heading_strategy=strat,
            heading_fixed_level=fixed,
            heading_single_child=single,
            get_pipeline=get_pipeline,
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
            detail="标题预切分 + 文档分段推理失败：%s" % (e,),
        ) from e
