"""最小可用的 Okapi BM25（无第三方依赖），用于与向量召回做混合检索。"""

from __future__ import annotations

import math
from collections import Counter

from lectureqa.textutils import tokenize


class BM25Index:
    def __init__(self, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_tokens: list[Counter[str]] = [Counter(tokenize(doc)) for doc in documents]
        self.doc_len = [sum(counter.values()) for counter in self.doc_tokens]
        self.avg_len = (sum(self.doc_len) / len(self.doc_len)) if self.doc_len else 0.0
        self._df: Counter[str] = Counter()
        for counter in self.doc_tokens:
            self._df.update(counter.keys())
        self.n_docs = len(documents)

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> list[float]:
        query_terms = Counter(tokenize(query))
        if not query_terms or not self.n_docs:
            return [0.0] * self.n_docs
        results: list[float] = []
        for doc_index, counter in enumerate(self.doc_tokens):
            length_norm = 1 - self.b + self.b * (self.doc_len[doc_index] / (self.avg_len or 1.0))
            score = 0.0
            for term, _query_tf in query_terms.items():
                tf = counter.get(term, 0)
                if tf == 0:
                    continue
                score += self._idf(term) * (tf * (self.k1 + 1)) / (tf + self.k1 * length_norm)
            results.append(score)
        return results

    def search(self, query: str, k: int, *, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        scores = self.scores(query)
        candidates = (
            [(index, score) for index, score in enumerate(scores) if index in allowed]
            if allowed is not None
            else list(enumerate(scores))
        )
        candidates = [(index, score) for index, score in candidates if score > 0]
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[:k]
