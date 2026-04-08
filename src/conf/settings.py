"""应用配置：从环境变量 / 项目根目录 `.env` 加载，统一 LLM、ES、切分与向量相关命名。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import quote

from pydantic import AliasChoices, Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import PydanticBaseSettingsSource

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """MVP 所需配置；未列出的历史变量（如 MYSQL_*）会被忽略。"""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # 允许字段名以 model_ 开头（如 model_api_key），避免与 Pydantic 保留前缀冲突
        protected_namespaces=("settings_",),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """pytest 执行用例时跳过 `.env`，仅使用进程环境变量（由 `monkeypatch` 控制）。"""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return (init_settings, env_settings, file_secret_settings)
        return (init_settings, env_settings, dotenv_settings, file_secret_settings)

    # --- LLM（OpenAI 兼容接口）---
    model_api_key: str = Field(
        ...,
        validation_alias=AliasChoices("MODEL_API_KEY", "OPENAI_API_KEY"),
        description="LLM API Key",
    )
    model_base_url: str = Field(
        ...,
        validation_alias="MODEL_BASE_URL",
        description="OpenAI 兼容 API Base URL",
    )
    model_name: str = Field(
        ...,
        validation_alias="MODEL_NAME",
        description="聊天模型名",
    )

    # --- Elasticsearch ---
    es_host: str = Field(default="localhost", validation_alias="ES_HOST")
    es_port: int = Field(default=9200, validation_alias="ES_PORT")
    es_index: str = Field(default="rag_law_doc_chunks", validation_alias="ES_INDEX")
    es_user: Optional[str] = Field(default=None, validation_alias="ES_USER")
    es_password: Optional[str] = Field(default=None, validation_alias="ES_PASSWORD")
    es_use_ssl: bool = Field(default=False, validation_alias="ES_USE_SSL")

    # --- 切分与检索 ---
    chunk_size: int = Field(
        default=1500,
        ge=1,
        validation_alias=AliasChoices("CHUNK_SIZE", "PARENT_CHUNK_SIZE"),
        description="字符滑窗单块长度（与旧名 PARENT_CHUNK_SIZE 二选一）",
    )
    chunk_overlap: int = Field(
        default=100,
        ge=0,
        validation_alias="CHUNK_OVERLAP",
    )
    chunk_overlap_min: Optional[int] = Field(
        default=None,
        ge=0,
        validation_alias="CHUNK_OVERLAP_MIN",
        description="句边界对齐时与上一块重叠的最低字符数；未设置时等于 CHUNK_OVERLAP（滑窗目标重叠）",
    )
    chunk_overlap_max: Optional[int] = Field(
        default=None,
        ge=0,
        validation_alias="CHUNK_OVERLAP_MAX",
        description="句边界对齐时与上一块重叠的最高字符数；未设置时等于 CHUNK_OVERLAP",
    )
    retrieval_k: int = Field(
        default=5,
        ge=1,
        validation_alias="RETRIEVAL_K",
        description="kNN / 检索返回条数",
    )
    qa_max_context_chars: int = Field(
        default=1200,
        ge=1,
        validation_alias="QA_MAX_CONTEXT_CHARS",
        description="问答时每条检索片段正文的最大字符数（超出截断，避免 prompt 过长）",
    )
    chunk_boundary_max_scan: Optional[int] = Field(
        default=None,
        ge=1,
        validation_alias="CHUNK_BOUNDARY_MAX_SCAN",
        description="句边界扩展扫描半径（字符）；未设置时取 min(CHUNK_SIZE, 800)",
    )
    chunk_boundary_priority_overlap: bool = Field(
        default=False,
        validation_alias="CHUNK_BOUNDARY_PRIORITY_OVERLAP",
        description="为 True 时句首对齐优先于重叠区间（允许实际重叠越出 MIN/MAX）",
    )
    chunk_boundary_clamp_adjust_max_rounds: int = Field(
        default=2,
        ge=1,
        le=8,
        validation_alias="CHUNK_BOUNDARY_CLAMP_ADJUST_MAX_ROUNDS",
        description="重叠夹紧与句首二次对齐的最大往返轮数",
    )

    # --- 向量模型 ---
    bge_m3_path: str = Field(..., validation_alias="BGE_M3_PATH")
    embedding_device: Optional[str] = Field(
        default=None,
        validation_alias="BGE_EMBEDDING_DEVICE",
        description="可选：强制编码设备，如 cpu、mps、cuda:0；未设置时由 FlagEmbedding 自动选择",
    )
    embedding_batch_size: int = Field(
        default=32,
        ge=1,
        validation_alias="EMBEDDING_BATCH_SIZE",
    )

    # --- 日志（loguru）；详见 doc/plan/v1.1.0-logging-plan.md ---
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_format: Literal["text", "json"] = Field(default="text", validation_alias="LOG_FORMAT")
    log_file: Optional[str] = Field(default=None, validation_alias="LOG_FILE")
    qa_audit_log_file: Optional[str] = Field(
        default="logs/qa-audit.log",
        validation_alias="QA_AUDIT_LOG_FILE",
    )

    # --- QA 监控 JSONL / ES；详见 doc/plan/v1.1.1-monitoring-plan.md §1.1 ---
    monitor_log_file: Optional[str] = Field(
        default="logs/monitor.log",
        validation_alias="MONITOR_LOG_FILE",
        description="JSONL 路径；空字符串关闭落盘",
    )
    monitor_es_index: str = Field(
        default="rag-law-monitor",
        validation_alias="MONITOR_ES_INDEX",
        description="监控文档写入的 ES 索引名（与 ES_INDEX 文档块索引分离）",
    )
    monitor_es_enabled: bool = Field(
        default=False,
        validation_alias="MONITOR_ES_ENABLED",
        description="为 True 时将监控记录写入 monitor_es_index",
    )
    token_cost_enabled: bool = Field(
        default=True,
        validation_alias="TOKEN_COST_ENABLED",
        description="为 True 时尝试从 LLM usage 与价格表计算单次 token 成本",
    )
    token_price_doc: str = Field(
        default="doc/price_api/qwen.md",
        validation_alias="TOKEN_PRICE_DOC",
        description="价格文档路径（相对项目根或绝对路径）",
    )
    token_price_region: str = Field(
        default="中国内地",
        validation_alias="TOKEN_PRICE_REGION",
        description="价格区域（当前支持从 qwen.md 提取中国内地区段）",
    )
    token_price_version: str = Field(
        default="qwen-md-v1",
        validation_alias="TOKEN_PRICE_VERSION",
        description="价格版本标识，写入监控文档便于回溯",
    )
    model_config_path: str = Field(
        default="settings/qwen_model/qwen_free_model_name_ranked.json",
        validation_alias="MODEL_CONFIG_PATH",
        description="模型配置文件路径（相对项目根或绝对路径）",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, v: object) -> str:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "INFO"
        s = str(v).strip().upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if s not in allowed:
            raise ValueError(
                "LOG_LEVEL 必须是 %s 之一（当前 %r）" % (", ".join(sorted(allowed)), v)
            )
        return s

    @field_validator("log_format", mode="before")
    @classmethod
    def _normalize_log_format(cls, v: object) -> str:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return "text"
        s = str(v).strip().lower()
        if s not in ("text", "json"):
            raise ValueError("LOG_FORMAT 必须是 text 或 json（当前 %r）" % (v,))
        return s

    @model_validator(mode="after")
    def _validate_overlap_vs_size(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                "CHUNK_OVERLAP 必须小于 CHUNK_SIZE（当前 overlap=%s, size=%s）"
                % (self.chunk_overlap, self.chunk_size)
            )
        if self.chunk_overlap_min is not None and self.chunk_overlap_min > self.chunk_overlap:
            raise ValueError(
                "CHUNK_OVERLAP_MIN 不能大于 CHUNK_OVERLAP（当前 min=%s, overlap=%s）"
                % (self.chunk_overlap_min, self.chunk_overlap)
            )
        floor = self.chunk_overlap if self.chunk_overlap_min is None else self.chunk_overlap_min
        ceiling = self.chunk_overlap if self.chunk_overlap_max is None else self.chunk_overlap_max
        if ceiling < floor:
            raise ValueError(
                "CHUNK_OVERLAP_MAX 不能小于有效重叠下界（当前 max=%s, floor=%s）"
                % (self.chunk_overlap_max, floor)
            )
        if ceiling >= self.chunk_size:
            raise ValueError(
                "CHUNK_OVERLAP_MAX 必须小于 CHUNK_SIZE（当前 max=%s, size=%s）"
                % (ceiling, self.chunk_size)
            )
        if self.chunk_boundary_max_scan is not None:
            if self.chunk_boundary_max_scan > self.chunk_size:
                raise ValueError(
                    "CHUNK_BOUNDARY_MAX_SCAN 不能大于 CHUNK_SIZE（当前 scan=%s, size=%s）"
                    % (self.chunk_boundary_max_scan, self.chunk_size)
                )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def log_file_resolved(self) -> Optional[Path]:
        """`LOG_FILE` 解析为绝对路径；未设置或空字符串时为 None。"""
        if self.log_file is None:
            return None
        raw = str(self.log_file).strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (_PROJECT_ROOT / p).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def monitor_log_file_resolved(self) -> Optional[Path]:
        """`MONITOR_LOG_FILE` 解析为绝对路径；未设置或空字符串时为 None。"""
        if self.monitor_log_file is None:
            return None
        raw = str(self.monitor_log_file).strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (_PROJECT_ROOT / p).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def qa_audit_log_file_resolved(self) -> Optional[Path]:
        """`QA_AUDIT_LOG_FILE` 解析为绝对路径；未设置或空字符串时为 None。"""
        if self.qa_audit_log_file is None:
            return None
        raw = str(self.qa_audit_log_file).strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (_PROJECT_ROOT / p).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def token_price_doc_resolved(self) -> Path:
        """`TOKEN_PRICE_DOC` 解析为绝对路径。"""
        raw = str(self.token_price_doc).strip()
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (_PROJECT_ROOT / p).resolve()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def model_config_path_resolved(self) -> Path:
        """`MODEL_CONFIG_PATH` 解析为绝对路径。"""
        raw = str(self.model_config_path).strip()
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (_PROJECT_ROOT / p).resolve()

    def load_model_config(self) -> dict:
        """加载模型配置文件内容；文件不存在返回空字典。"""
        import json
        path = self.model_config_path_resolved
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def chunk_overlap_floor(self) -> int:
        """句边界对齐时块链重叠下界；未配置 CHUNK_OVERLAP_MIN 时与滑窗目标重叠一致。"""
        return self.chunk_overlap if self.chunk_overlap_min is None else self.chunk_overlap_min

    @computed_field  # type: ignore[prop-decorator]
    @property
    def chunk_overlap_ceiling(self) -> int:
        """句边界对齐时块链重叠上界；未配置 CHUNK_OVERLAP_MAX 时与滑窗目标重叠一致。"""
        return self.chunk_overlap if self.chunk_overlap_max is None else self.chunk_overlap_max

    @computed_field  # type: ignore[prop-decorator]
    @property
    def chunk_boundary_max_scan_effective(self) -> int:
        """扩展扫描半径：未配置时 min(CHUNK_SIZE, 800)，且不超过 chunk_size。"""
        cap = self.chunk_boundary_max_scan
        if cap is None:
            return min(self.chunk_size, 800)
        return min(self.chunk_size, cap)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def es_scheme(self) -> str:
        return "https" if self.es_use_ssl else "http"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def es_url(self) -> str:
        """供 `elasticsearch` 等客户端使用的 URL。"""
        user, password = self.es_user, self.es_password
        if user is not None and password is not None:
            u = quote(user, safe="")
            p = quote(password, safe="")
            netloc = f"{u}:{p}@{self.es_host}:{self.es_port}"
        else:
            netloc = f"{self.es_host}:{self.es_port}"
        return f"{self.es_scheme}://{netloc}"


@lru_cache
def get_settings() -> Settings:
    """进程内单例配置（可测时通过 get_settings.cache_clear() 刷新）。"""
    return Settings()


def project_root() -> Path:
    """仓库根目录（含 `data/`、`.env`）。"""
    return _PROJECT_ROOT
