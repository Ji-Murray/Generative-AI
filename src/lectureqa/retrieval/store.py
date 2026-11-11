"""向量库后端：ChromaDB（默认）与纯 numpy（兜底）。

统一的对外契约只有三个动作：reset / add / query(向量, k, doc 过滤) → [(chunk_id, 余弦相似度)]。
上层检索器只依赖这个契约，因此换后端不影响任何业务逻辑。
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Protocol

from lectureqa.config import Settings
from lectureqa.schemas import Chunk


class VectorStore(Protocol):
    backend: str

    def reset(self) -> None: ...

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    def query(
        self, vector: list[float], k: int, doc_ids: list[str] | None = None
    ) -> list[tuple[str, float]]: ...

    def count(self) -> int: ...


class LocalStore:
    """numpy 余弦检索，索引落盘为 vectors.npy + ids.json。"""

    backend = "local"

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.vectors_path = directory / "vectors.npy"
        self.ids_path = directory / "ids.json"
        self._matrix = None
        self._ids: list[str] = []
        self._load()

    def _load(self) -> None:
        import numpy as np

        if self.vectors_path.exists() and self.ids_path.exists():
            self._matrix = np.load(self.vectors_path)
            self._ids = json.loads(self.ids_path.read_text(encoding="utf-8"))

    def reset(self) -> None:
        for path in (self.vectors_path, self.ids_path):
            path.unlink(missing_ok=True)
        self._matrix = None
        self._ids = []

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        import numpy as np

        if not chunks:
            return
        new_matrix = np.asarray(vectors, dtype="float32")
        norms = np.linalg.norm(new_matrix, axis=1, keepdims=True)
        new_matrix = new_matrix / np.clip(norms, 1e-12, None)
        if self._matrix is None:
            self._matrix = new_matrix
        else:
            self._matrix = np.vstack([self._matrix, new_matrix])
        self._ids.extend(chunk.chunk_id for chunk in chunks)
        np.save(self.vectors_path, self._matrix)
        self.ids_path.write_text(json.dumps(self._ids), encoding="utf-8")

    def query(
        self, vector: list[float], k: int, doc_ids: list[str] | None = None
    ) -> list[tuple[str, float]]:
        import numpy as np

        if self._matrix is None or not self._ids:
            return []
        query = np.asarray(vector, dtype="float32")
        query = query / max(float(np.linalg.norm(query)), 1e-12)
        scores = self._matrix @ query
        if doc_ids:
            allowed = set(doc_ids)
            mask = np.array([chunk_id.split(":")[0] in allowed for chunk_id in self._ids])
            scores = np.where(mask, scores, -np.inf)
        order = np.argsort(-scores)[:k]
        return [(self._ids[i], float(scores[i])) for i in order if scores[i] > -np.inf]

    def count(self) -> int:
        return len(self._ids)


class ChromaStore:
    backend = "chroma"

    def __init__(self, settings: Settings) -> None:
        import chromadb

        settings.collection_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(settings.collection_dir))
        self._name = settings.collection
        self._collection = self._get_or_create()

    def _get_or_create(self):
        return self._client.get_or_create_collection(
            name=self._name, metadata={"hnsw:space": "cosine"}
        )

    def reset(self) -> None:
        with contextlib.suppress(Exception):  # 集合不存在时忽略
            self._client.delete_collection(self._name)
        self._collection = self._get_or_create()

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if not chunks:
            return
        batch = 256
        for start in range(0, len(chunks), batch):
            slice_ = chunks[start : start + batch]
            self._collection.add(
                ids=[chunk.chunk_id for chunk in slice_],
                embeddings=vectors[start : start + batch],
                documents=[chunk.text for chunk in slice_],
                metadatas=[
                    {
                        "doc_id": chunk.doc_id,
                        "doc_title": chunk.doc_title,
                        "page": chunk.page,
                        "chunk_index": chunk.chunk_index,
                    }
                    for chunk in slice_
                ],
            )

    def query(
        self, vector: list[float], k: int, doc_ids: list[str] | None = None
    ) -> list[tuple[str, float]]:
        where = {"doc_id": {"$in": list(doc_ids)}} if doc_ids else None
        result = self._collection.query(
            query_embeddings=[vector],
            n_results=max(k, 1),
            where=where,
            include=["distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            (chunk_id, 1.0 - float(distance))
            for chunk_id, distance in zip(ids, distances, strict=False)
        ]

    def count(self) -> int:
        return int(self._collection.count())


def make_store(settings: Settings) -> VectorStore:
    if settings.store_backend == "local":
        return LocalStore(settings.local_index_dir)
    try:
        return ChromaStore(settings)
    except Exception as exc:  # noqa: BLE001 - chromadb 缺失/损坏时自动降级
        import warnings

        warnings.warn(f"ChromaDB 不可用（{exc}），已降级为本地 numpy 索引", stacklevel=2)
        return LocalStore(settings.local_index_dir)
