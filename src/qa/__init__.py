"""RAG 问答：提示拼接与在线流水线。"""

from __future__ import annotations

from qa.messages import DEFAULT_SYSTEM_PROMPT, build_messages, build_user_content
from qa.pipeline import answer_question

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "answer_question",
    "build_messages",
    "build_user_content",
]
