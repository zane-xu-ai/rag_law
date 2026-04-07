"""Aliyun OSS Python SDK v2 client helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# `src/utils/oss_aliyun/client.py` -> parents[3] = 仓库根（含 `.env`）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DOTENV_LOADED = False


def _ensure_dotenv_loaded() -> None:
    """将项目根目录 `.env` 注入进程环境（与 `conf.settings.Settings` 一致）。

    未调用 `get_settings()` 时，单独运行 `python -m utils.oss_aliyun.cli` 也会读到 `.env`。
    测试进程（`PYTEST_CURRENT_TEST`）下跳过，避免与 `monkeypatch` 冲突。
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = _PROJECT_ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _require_env(name: str, fallback: str | None = None) -> str:
    val = os.getenv(name)
    if val:
        return val
    if fallback:
        val2 = os.getenv(fallback)
        if val2:
            return val2
    fb = f" or {fallback}" if fallback else ""
    raise RuntimeError(f"Missing required env: {name}{fb}")


def _import_oss() -> Any:
    try:
        import alibabacloud_oss_v2 as oss  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError(
            "alibabacloud-oss-v2 is required. Install with: pip install alibabacloud-oss-v2"
        ) from exc
    return oss


@dataclass(frozen=True)
class OssEnvConfig:
    region: str
    endpoint: str | None

    @staticmethod
    def from_env() -> "OssEnvConfig":
        region = _require_env("OSS_REGION")
        endpoint = os.getenv("OSS_ENDPOINT") or None
        return OssEnvConfig(region=region, endpoint=endpoint)


def build_client_from_env() -> Any:
    """Build OSS v2 client from environment variables.

    Required:
    - OSS_REGION
    - OSS_ACCESS_KEY_ID (or accessKeyId for compatibility)
    - OSS_ACCESS_KEY_SECRET (or accessKeySecret for compatibility)

    Optional:
    - OSS_ENDPOINT

    若已在 shell 中 export，则直接使用；否则会尝试加载仓库根目录 `.env`（不覆盖已有环境变量）。
    """
    _ensure_dotenv_loaded()
    # Ensure credential envs exist first (SDK provider reads them by name).
    key_id = os.getenv("OSS_ACCESS_KEY_ID") or os.getenv("accessKeyId")
    key_secret = os.getenv("OSS_ACCESS_KEY_SECRET") or os.getenv("accessKeySecret")
    if not key_id or not key_secret:
        raise RuntimeError(
            "Missing OSS credentials env. Set OSS_ACCESS_KEY_ID/OSS_ACCESS_KEY_SECRET "
            "(or legacy accessKeyId/accessKeySecret)."
        )
    # Standardize into official env names expected by EnvironmentVariableCredentialsProvider.
    os.environ["OSS_ACCESS_KEY_ID"] = key_id
    os.environ["OSS_ACCESS_KEY_SECRET"] = key_secret

    cfg_env = OssEnvConfig.from_env()
    oss = _import_oss()
    provider = oss.credentials.EnvironmentVariableCredentialsProvider()
    cfg = oss.config.load_default()
    cfg.credentials_provider = provider
    cfg.region = cfg_env.region
    if cfg_env.endpoint:
        cfg.endpoint = cfg_env.endpoint
    return oss.Client(cfg)

