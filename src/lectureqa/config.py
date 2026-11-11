"""集中式配置：所有可调参数都来自 .env，代码里不出现魔法数字。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- LLM ----------
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1600
    llm_timeout: float = 180.0

    # ---------- Embedding ----------
    embedding_provider: Literal["openai", "hash", "chroma"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 512
    # 不同服务商的单次 embed 批量上限不同（Qwen 为 25），默认留余量
    embedding_batch_size: int = 16

    # ---------- 向量库 ----------
    store_backend: Literal["chroma", "local"] = "chroma"
    index_dir: Path = PROJECT_ROOT / "var" / "index"
    collection: str = "lectureqa"

    # ---------- 语料与分块 ----------
    data_dir: Path = PROJECT_ROOT / "data"
    upload_dir: Path = PROJECT_ROOT / "var" / "uploads"
    learning_dir: Path = PROJECT_ROOT / "var" / "learning"
    max_upload_mb: int = 30
    chunk_size: int = 900
    chunk_overlap: int = 150
    min_chunk_chars: int = 40

    # ---------- 检索 ----------
    fetch_k: int = 30
    top_k: int = 6
    rerank: Literal["coverage", "cross-encoder", "none"] = "coverage"
    rerank_model: str = "BAAI/bge-reranker-base"
    rrf_k: int = 60
    min_evidence_score: float = 0.30

    # ---------- 生成 ----------
    default_language: Literal["auto", "zh", "en"] = "auto"
    quiz_max_questions: int = 10
    summary_max_tokens: int = 2400

    # ---------- 外部补充（可选，默认关闭） ----------
    web_fallback: Literal["off", "wikipedia"] = "off"
    web_lang: Literal["auto", "zh", "en"] = "auto"
    web_max_results: int = 3
    web_timeout: float = 8.0
    web_min_coverage: float = 0.30

    # ---------- 评估 ----------
    eval_judge_model: str | None = None

    @field_validator("index_dir", "data_dir", "upload_dir", "learning_dir", mode="after")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        value = value.expanduser()
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @field_validator("chunk_overlap", mode="after")
    @classmethod
    def _overlap_lt_size(cls, value: int, info) -> int:
        size = info.data.get("chunk_size")
        if size and value >= size:
            raise ValueError("CHUNK_OVERLAP 必须小于 CHUNK_SIZE")
        return value

    # ---------- 派生路径 ----------
    @property
    def chunks_path(self) -> Path:
        return self.index_dir / "chunks.jsonl"

    @property
    def manifest_path(self) -> Path:
        return self.index_dir / "manifest.json"

    @property
    def collection_dir(self) -> Path:
        return self.index_dir / "chroma"

    @property
    def local_index_dir(self) -> Path:
        return self.index_dir / "local"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key) and not self.llm_api_key.startswith("sk-replace")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
