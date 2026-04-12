"""文档分段（方案 D）pipeline 按模型目录缓存；供 chunking / qa WebUI 共用，避免重复加载权重。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_pipelines: dict[str, Any] = {}


def clear_document_segmentation_pipeline_cache() -> None:
    """测试或热切换模型目录时清空缓存。"""
    with _lock:
        _pipelines.clear()


def get_or_build_document_segmentation_pipeline(model_dir: Path) -> Any:
    """按模型目录缓存 pipeline；首次加载可能较慢。"""
    key = str(model_dir.expanduser().resolve())
    with _lock:
        if key not in _pipelines:
            from chunking.document_segmentation import build_document_segmentation_pipeline

            _pipelines[key] = build_document_segmentation_pipeline(key)
        return _pipelines[key]
