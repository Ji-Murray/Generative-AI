"""Embedding 提供方抽象。

三种实现共用同一契约，切换只改 .env：
- openai：走 LLM_BASE_URL 的 /embeddings（生产默认）
- hash  ：本地确定性哈希向量，零依赖、离线可跑（CI / 断网演示）
- chroma：ChromaDB 内置 ONNX 模型（all-MiniLM-L6-v2）
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Protocol

from lectureqa.config import Settings
from lectureqa.textutils import tokenize


class Embedder(Protocol):
    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """特征哈希 + 符号散列 + L2 归一化。

    不是语义模型，但能稳定地把「词面重叠」映射成余弦相似度，
    在没有 API Key 或 CI 环境里保证整条链路可运行、结果可复现。
    """

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.name = f"hash-{dim}"

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            weight = 1.0 if len(token) > 1 else 0.5
            vector[bucket] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class OpenAIEmbedder:
    def __init__(self, settings: Settings, *, batch_size: int | None = None) -> None:
        self.settings = settings
        self.model = settings.embedding_model
        self.batch_size = max(1, batch_size or settings.embedding_batch_size)
        self.name = f"openai:{self.model}"
        self._client = None

    def _sdk(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
                timeout=self.settings.llm_timeout,
            )
        return self._client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            response = self._sdk().embeddings.create(model=self.model, input=batch)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend([list(item.embedding) for item in ordered])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


class ChromaDefaultEmbedder:
    """Chroma 自带的 ONNX all-MiniLM-L6-v2，首次调用会下载模型。"""

    def __init__(self) -> None:
        self.name = "chroma:default"
        self._fn = None

    def _function(self):
        if self._fn is None:
            from chromadb.utils import embedding_functions

            self._fn = embedding_functions.DefaultEmbeddingFunction()
        return self._fn

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(vector) for vector in self._function()(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


def make_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hash":
        return HashEmbedder(dim=settings.embedding_dim)
    if settings.embedding_provider == "chroma":
        return ChromaDefaultEmbedder()
    return OpenAIEmbedder(settings)
