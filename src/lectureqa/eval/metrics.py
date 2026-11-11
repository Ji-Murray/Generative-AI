"""评估指标：全部是纯函数，便于单元测试与在技术报告中引用。"""

from __future__ import annotations

from statistics import mean

from lectureqa.schemas import Citation, ItemResult, RetrievedChunk
from lectureqa.textutils import slugify


def _norm(doc_id: str) -> str:
    """gold 标注写 lecture01_transformer，索引里是 lecture01-transformer，比较前统一归一化。"""
    return slugify(doc_id, max_len=120)


def _doc_match(chunk_doc: str, gold_doc_ids: list[str]) -> bool:
    if not gold_doc_ids:
        return True
    return _norm(chunk_doc) in {_norm(doc) for doc in gold_doc_ids}


def matched_pages(
    retrieved: list[RetrievedChunk], gold_pages: list[int], gold_doc_ids: list[str]
) -> set[int]:
    hits: set[int] = set()
    for item in retrieved:
        chunk = item.chunk
        if chunk.page not in gold_pages:
            continue
        if not _doc_match(chunk.doc_id, gold_doc_ids):
            continue
        hits.add(chunk.page)
    return hits


def hit_at_k(retrieved: list[RetrievedChunk], gold_pages: list[int], gold_doc_ids: list[str]) -> bool:
    return bool(matched_pages(retrieved, gold_pages, gold_doc_ids))


def recall_at_k(retrieved: list[RetrievedChunk], gold_pages: list[int], gold_doc_ids: list[str]) -> float:
    gold = set(gold_pages)
    if not gold:
        return 0.0
    return len(matched_pages(retrieved, gold_pages, gold_doc_ids)) / len(gold)


def reciprocal_rank(
    retrieved: list[RetrievedChunk], gold_pages: list[int], gold_doc_ids: list[str]
) -> float:
    gold = set(gold_pages)
    for rank, item in enumerate(retrieved, start=1):
        chunk = item.chunk
        if chunk.page in gold and _doc_match(chunk.doc_id, gold_doc_ids):
            return 1.0 / rank
    return 0.0


def citation_precision(
    citations: list[Citation], gold_pages: list[int], gold_doc_ids: list[str]
) -> float:
    if not citations:
        return 0.0
    gold = set(gold_pages)
    correct = sum(
        1
        for citation in citations
        if citation.page in gold and _doc_match(citation.doc_id, gold_doc_ids)
    )
    return correct / len(citations)


def refusal_accuracy(results: list[ItemResult]) -> float:
    scored = [item for item in results if not item.error]
    if not scored:
        return 0.0
    correct = 0
    for item in scored:
        expected_refusal = item.type == "unanswerable"
        correct += int(item.refused == expected_refusal)
    return correct / len(scored)


def aggregate(results: list[ItemResult]) -> dict[str, float]:
    answerable = [item for item in results if item.type == "answerable" and not item.error]
    unanswerable = [item for item in results if item.type == "unanswerable" and not item.error]
    judged = [item.judge_score for item in results if item.judge_score is not None]
    metrics = {
        "n": float(len(results)),
        "n_scored": float(sum(not item.error for item in results)),
        "n_answerable": float(len(answerable)),
        "n_unanswerable": float(len(unanswerable)),
        "hit_rate": mean([float(item.hit_at_k) for item in answerable]) if answerable else 0.0,
        "recall": mean([item.recall_at_k for item in answerable]) if answerable else 0.0,
        "mrr": mean([item.reciprocal_rank for item in answerable]) if answerable else 0.0,
        "citation_precision": (
            mean([item.citation_precision for item in answerable]) if answerable else 0.0
        ),
        "grounded_rate": mean([float(item.grounded) for item in answerable]) if answerable else 0.0,
        "refusal_accuracy": refusal_accuracy(results),
        "unanswerable_refusal_rate": (
            mean([float(item.refused) for item in unanswerable]) if unanswerable else 0.0
        ),
        "avg_latency_ms": mean([item.latency_ms for item in results]) if results else 0.0,
        "error_rate": mean([float(bool(item.error)) for item in results]) if results else 0.0,
    }
    if judged:
        metrics["judge_score"] = mean(judged)
    return {key: round(value, 4) for key, value in metrics.items()}
