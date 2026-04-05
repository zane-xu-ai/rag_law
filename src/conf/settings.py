"""应用配置：从环境变量 / 项目根目录 `.env` 加载，统一 LLM、ES、切分与向量相关命名。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from pydantic import AliasChoices, Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """MVP 所需配置；未列出的历史变量（如 MYSQL_*）会被忽略。"""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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
    es_index: str = Field(default="rag_law_chunks", validation_alias="ES_INDEX")
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
        default=50,
        ge=0,
        validation_alias="CHUNK_OVERLAP",
    )
    retrieval_k: int = Field(
        default=5,
        ge=1,
        validation_alias="RETRIEVAL_K",
        description="kNN / 检索返回条数",
    )

    # --- 向量模型 ---
    bge_m3_path: str = Field(..., validation_alias="BGE_M3_PATH")
    embedding_batch_size: int = Field(
        default=32,
        ge=1,
        validation_alias="EMBEDDING_BATCH_SIZE",
    )

    @model_validator(mode="after")
    def _validate_overlap_vs_size(self) -> Settings:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                "CHUNK_OVERLAP 必须小于 CHUNK_SIZE（当前 overlap=%s, size=%s）"
                % (self.chunk_overlap, self.chunk_size)
            )
        return self

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
