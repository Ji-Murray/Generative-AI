"""混合检索：向量召回 + BM25 召回 → RRF 融合 → 重排 → 证据支持度。"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from lectureqa.config import Settings
from lectureqa.retrieval.corpus import Corpus
from lectureqa.retrieval.embeddings import Embedder
from lectureqa.retrieval.query_rewrite import lexical_expand
from lectureqa.retrieval.rerank import Reranker, coverage_score
from lectureqa.retrieval.store import VectorStore
from lectureqa.schemas import RetrievedChunk

logger = logging.getLogger(__name__)


def _dense_to_support(similarity: float) -> float:
    """把余弦相似度映射到 0~1 的支持度，余弦 0.2→0，0.8→1。"""
    return max(0.0, min(1.0, (similarity - 0.2) / 0.6))


def _lexical_to_support(score: float | None) -> float:
    """把较强的 BM25 分映射到 0~1；弱命中视为噪音，避免无关中文问句误过门槛。"""
    if score is None or score < 3.0:
        return 0.0
    return max(0.0, min(1.0, (float(score) - 3.0) / 5.0))


class Retriever:
    def __init__(
        self,
        corpus: Corpus,
        store: VectorStore,
        embedder: Embedder,
        settings: Settings,
        reranker: Reranker | None = None,
    ) -> None:
        self.corpus = corpus
        self.store = store
        self.embedder = embedder
        self.settings = settings
        self.reranker = reranker
        self._dense_disabled = False

    # ------------------------------------------------------------------ 内部
    def _dense(self, query: str, k: int, doc_ids: list[str] | None) -> list[tuple[str, float]]:
        if self._dense_disabled or len(self.corpus) == 0:
            return []
        try:
            vector = self.embedder.embed_query(query)
            hits = self.store.query(vector, k, doc_ids)
        except Exception as exc:  # noqa: BLE001 - embedding 服务不可用时退化为纯词面检索
            logger.warning("向量召回不可用（%s），本次仅用 BM25", exc)
            self._dense_disabled = True
            return []
        return [(chunk_id, similarity) for chunk_id, similarity in hits if chunk_id in self.corpus.by_id]

    def _lexical(self, query: str, k: int, doc_ids: list[str] | None) -> list[tuple[str, float]]:
        allowed = self.corpus.filter_positions(doc_ids)
        hits = self.corpus.bm25.search(query, k, allowed=allowed)
        return [(self.corpus.chunks[position].chunk_id, score) for position, score in hits]

    def _fuse(self, runs: Iterable[list[tuple[str, float]]]) -> dict[str, float]:
        fused: dict[str, float] = {}
        for run in runs:
            for rank, (chunk_id, _score) in enumerate(run):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (self.settings.rrf_k + rank + 1)
        return fused

    # ------------------------------------------------------------------ 对外
    def retrieve(
        self,
        query: str,
        *,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
        fetch_k: int | None = None,
    ) -> list[RetrievedChunk]:
        query = query.strip()
        if not query or len(self.corpus) == 0:
            return []
        # 中文问句扩写英文术语，避免对英文课件时 BM25/覆盖度归零
        search_query = lexical_expand(query)
        top_k = top_k or self.settings.top_k
        fetch_k = max(fetch_k or self.settings.fetch_k, top_k)

        dense = self._dense(search_query, fetch_k, doc_ids)
        lexical = self._lexical(search_query, fetch_k, doc_ids)
        fused = self._fuse([dense, lexical])

        dense_map = dict(dense)
        lexical_map = dict(lexical)
        candidates: list[RetrievedChunk] = []
        for chunk_id, score in fused.items():
            chunk = self.corpus.by_id.get(chunk_id)
            if chunk is None:
                continue
            similarity = dense_map.get(chunk_id, 0.0)
            lexical_score = lexical_map.get(chunk_id)
            support = max(
                coverage_score(search_query, chunk.text),
                _dense_to_support(similarity),
                _lexical_to_support(lexical_score),
            )
            if support <= 0:
                # 既没有词面覆盖、也没有语义相似度，纯噪音，直接丢弃
                continue
            candidates.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=score,
                    dense_score=similarity if chunk_id in dense_map else None,
                    lexical_score=lexical_score,
                    support=support,
                )
            )

        if doc_ids:
            allowed_docs = set(doc_ids)
            candidates = [item for item in candidates if item.chunk.doc_id in allowed_docs]

        candidates.sort(key=lambda item: (item.score, item.support), reverse=True)
        if self.reranker is not None:
            return self.reranker.rerank(search_query, candidates, top_k)
        return candidates[:top_k]

    def best_support(self, results: list[RetrievedChunk]) -> float:
        return max((item.support for item in results), default=0.0)

    def summary_evidence(
        self,
        query: str,
        *,
        doc_ids: list[str] | None = None,
        per_doc: int | None = None,
        max_chars: int = 16000,
    ) -> list[RetrievedChunk]:
        """总结类问题：跨页扫描讲义，而不是只拿封面第 1 页。

        - 单讲：沿页码均匀抽样多块，覆盖整份 PPT
        - 多讲：每份取若干块，保证每份都出现
        预算用尽即停，避免提示词爆炸。
        """
        if len(self.corpus) == 0:
            return []
        search_query = lexical_expand(query)
        allowed = self.corpus.filter_positions(doc_ids)
        grouped: dict[str, list[int]] = {}
        for index, chunk in enumerate(self.corpus.chunks):
            if allowed is not None and index not in allowed:
                continue
            grouped.setdefault(chunk.doc_id, []).append(index)
        if not grouped:
            return []

        n_docs = len(grouped)
        if per_doc is None:
            # 单讲多抽；全课每讲少抽但仍覆盖
            per_doc = 18 if n_docs == 1 else max(3, min(8, 28 // n_docs))

        picks: list[int] = []
        seen: set[int] = set()
        total_chars = 0

        for positions in grouped.values():
            for position in _stratified_sample(positions, per_doc, self.corpus.chunks):
                if position in seen:
                    continue
                text_len = len(self.corpus.chunks[position].text)
                if picks and total_chars + text_len > max_chars:
                    break
                seen.add(position)
                picks.append(position)
                total_chars += text_len

        picks.sort()
        results: list[RetrievedChunk] = []
        for position in picks:
            chunk = self.corpus.chunks[position]
            # 总结场景按覆盖优先；无词面命中也保留（均匀抽样的页仍有信息）
            support = max(coverage_score(search_query, chunk.text), 0.5)
            results.append(RetrievedChunk(chunk=chunk, score=support, support=support))
        return results


def _chunk_substance(text: str) -> int:
    """粗略衡量一页是否有可总结的实质内容（跳过 Questions? / References 等薄页）。"""
    cleaned = " ".join((text or "").split())
    if len(cleaned) < 40:
        return 0
    lowered = cleaned.lower()
    if lowered in {"questions?", "questions", "references", "thank you", "thanks"}:
        return 0
    return len(cleaned)


def _stratified_sample(positions: list[int], k: int, chunks) -> list[int]:
    """按讲义顺序均匀取 k 块；落点若太薄则改取附近更有内容的页。"""
    if k <= 0 or not positions:
        return []
    if len(positions) <= k:
        return list(positions)
    if k == 1:
        return [_richest_near(positions, 0, chunks)]
    last = len(positions) - 1
    indexes = sorted({round(i * last / (k - 1)) for i in range(k)})
    picked: list[int] = []
    seen: set[int] = set()
    for index in indexes:
        position = _richest_near(positions, index, chunks)
        if position not in seen:
            seen.add(position)
            picked.append(position)
    return picked


def _richest_near(positions: list[int], center: int, chunks, radius: int = 2) -> int:
    best = positions[center]
    best_score = _chunk_substance(chunks[best].text)
    for offset in range(1, radius + 1):
        for index in (center - offset, center + offset):
            if 0 <= index < len(positions):
                candidate = positions[index]
                score = _chunk_substance(chunks[candidate].text)
                if score > best_score:
                    best = candidate
                    best_score = score
    return best
