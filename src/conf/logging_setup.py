"""loguru 单点初始化与标准库 logging 拦截（uvicorn / fastapi）。"""

from __future__ import annotations

import logging
import sys

from loguru import logger

from conf.settings import Settings

_configured = False


class InterceptHandler(logging.Handler):
    """将标准库 `logging` 记录转发到 loguru（与 loguru 文档常见用法一致）。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        depth = 2
        frame = logging.currentframe()
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _intercept_stdlib_logging() -> None:
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(0)
    for name in (
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "uvicorn.asgi",
        "fastapi",
    ):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True


def reset_logging_for_tests() -> None:
    """仅 pytest 使用：清空 loguru sink 与内部标志，便于反复调用 `configure_logging`。"""
    global _configured
    _configured = False
    logger.remove()


def configure_logging(settings: Settings, *, force: bool = False) -> None:
    """按 `Settings` 配置 loguru，并拦截 uvicorn/fastapi 使用的标准库 logging。

    进程内默认只完整执行一次；`force=True` 或先调用 `reset_logging_for_tests()` 可重新配置。
    """
    global _configured
    if _configured and not force:
        return

    logger.remove()
    level = settings.log_level

    serialize = settings.log_format == "json"
    kwargs: dict = {
        "level": level,
        "serialize": serialize,
        "filter": lambda r: not r["extra"].get("qa_audit", False),
    }
    if not serialize:
        kwargs["format"] = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        )

    logger.add(sys.stderr, **kwargs)

    log_path = settings.log_file_resolved
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_kw = dict(kwargs)
        file_kw["rotation"] = "10 MB"
        file_kw["retention"] = "7 days"
        # 文件日志保留全部事件（包括 qa_audit）
        file_kw.pop("filter", None)
        logger.add(str(log_path), **file_kw)

    qa_audit_log_path = settings.qa_audit_log_file_resolved
    if qa_audit_log_path is not None:
        qa_audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        # 审计日志强制 JSON，确保 extra 字段完整可见（session_id、query_text、retrieval 等）。
        audit_kw = {
            "level": level,
            "serialize": True,
            "rotation": "10 MB",
            "retention": "7 days",
            "filter": lambda r: bool(r["extra"].get("qa_audit", False)),
        }
        logger.add(str(qa_audit_log_path), **audit_kw)

    _intercept_stdlib_logging()
    _configured = True
