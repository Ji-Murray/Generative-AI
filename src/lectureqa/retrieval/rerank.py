"""重排（rerank）。

默认使用零依赖的「证据覆盖度」重排：问题中的实词在片段里被覆盖得越多、
越集中，越可能是答案出处。可选接入 cross-encoder（bge-reranker）获得语义级打分。
"""

from __future__ import annotations

import math
from typing import Protocol

from lectureqa.schemas import RetrievedChunk
from lectureqa.textutils import content_tokens, has_cjk


def _term_coverage(terms: list[str], haystack: str) -> float:
    if not terms:
        return 0.0
    unique = list(dict.fromkeys(terms))
    hit = sum(1 for term in unique if term in haystack)
    base = hit / len(unique)
    compact = "".join(unique)
    if len(compact) > 3 and compact in haystack.replace(" ", ""):
        base = min(1.0, base + 0.15)
    # 课件里常只出现 CNN / GNN 这类缩写；命中即给保底，避免同义词列表稀释分数
    acronyms = [term for term in unique if term.isascii() and term.isalpha() and 2 <= len(term) <= 5]
    if acronyms and any(term in haystack for term in acronyms):
        base = max(base, 0.35)
    return base


def coverage_score(query: str, text: str) -> float:
    """问题实词在片段中的覆盖比例（0~1）。

    中英混排时分别看拉丁词 / CJK 词的覆盖，取较高者，避免「中文问英文课件」
    被大量未命中的中文词元把分数拉到 0。
    """
    query_terms = [term for term in content_tokens(query) if len(term) > 1] or content_tokens(
        query
    )
    if not query_terms:
        return 0.0
    haystack = text.lower()
    overall = _term_coverage(query_terms, haystack)
    latin = [term for term in query_terms if not has_cjk(term)]
    cjk = [term for term in query_terms if has_cjk(term)]
    return max(overall, _term_coverage(latin, haystack), _term_coverage(cjk, haystack))


class Reranker(Protocol):
    name: str

    def rerank(
        self, query: str, candidates: list[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]: ...


class CoverageReranker:
    name = "coverage"

    def rerank(
        self, query: str, candidates: list[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []
        max_fused = max(candidate.score for candidate in candidates) or 1.0
        rescored: list[RetrievedChunk] = []
        for candidate in candidates:
            support = max(candidate.support, coverage_score(query, candidate.chunk.text))
            fused = candidate.score / max_fused
            rescored.append(
                candidate.model_copy(
                    update={"score": round(0.4 * fused + 0.6 * support, 6), "support": support}
                )
            )
        rescored.sort(key=lambda item: item.score, reverse=True)
        return rescored[:top_n]


class CrossEncoderReranker:
    name = "cross-encoder"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None
        self._fallback = CoverageReranker()

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self, query: str, candidates: list[RetrievedChunk], top_n: int
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []
        try:
            model = self._load()
        except Exception:  # noqa: BLE001 - 未安装 sentence-transformers 时平滑降级
            return self._fallback.rerank(query, candidates, top_n)
        pairs = [(query, candidate.chunk.text) for candidate in candidates]
        scores = model.predict(pairs)
        rescored = []
        for candidate, raw in zip(candidates, scores, strict=False):
            probability = 1.0 / (1.0 + math.exp(-float(raw)))
            rescored.append(
                candidate.model_copy(update={"score": probability, "support": probability})
            )
        rescored.sort(key=lambda item: item.score, reverse=True)
        return rescored[:top_n]


def make_reranker(settings) -> Reranker | None:
    if settings.rerank == "none":
        return None
    if settings.rerank == "cross-encoder":
        return CrossEncoderReranker(settings.rerank_model)
    return CoverageReranker()
