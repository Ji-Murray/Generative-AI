"""语料库：chunks.jsonl 是唯一事实源，向量库只是它的索引副本。"""

from __future__ import annotations

import json
from pathlib import Path

from lectureqa.retrieval.bm25 import BM25Index
from lectureqa.schemas import Chunk, DocumentInfo


class Corpus:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.by_id = {chunk.chunk_id: chunk for chunk in chunks}
        self.position = {chunk.chunk_id: index for index, chunk in enumerate(chunks)}
        self._bm25: BM25Index | None = None

    @classmethod
    def load(cls, chunks_path: Path) -> Corpus:
        if not chunks_path.exists():
            return cls([])
        chunks: list[Chunk] = []
        with chunks_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    chunks.append(Chunk.model_validate(json.loads(line)))
        return cls(chunks)

    def __len__(self) -> int:
        return len(self.chunks)

    @property
    def bm25(self) -> BM25Index:
        if self._bm25 is None:
            self._bm25 = BM25Index([chunk.text for chunk in self.chunks])
        return self._bm25

    def doc_ids(self) -> list[str]:
        seen: dict[str, None] = {}
        for chunk in self.chunks:
            seen.setdefault(chunk.doc_id, None)
        return list(seen)

    def documents(self) -> list[DocumentInfo]:
        grouped: dict[str, list[Chunk]] = {}
        for chunk in self.chunks:
            grouped.setdefault(chunk.doc_id, []).append(chunk)
        documents: list[DocumentInfo] = []
        for doc_id, items in grouped.items():
            documents.append(
                DocumentInfo(
                    doc_id=doc_id,
                    doc_title=items[0].doc_title,
                    source_path="",
                    pages=max(chunk.page for chunk in items),
                    chunks=len(items),
                )
            )
        return documents

    def filter_positions(self, doc_ids: list[str] | None) -> set[int] | None:
        if not doc_ids:
            return None
        allowed = set(doc_ids)
        return {
            index
            for index, chunk in enumerate(self.chunks)
            if chunk.doc_id in allowed
        }
