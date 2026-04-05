"""pytest 公共 fixture。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from conf.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """避免 `get_settings` 的 lru_cache 在用例间串味。"""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
