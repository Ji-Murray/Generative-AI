from __future__ import annotations

from lectureqa.eval.metrics import (
    aggregate,
    citation_precision,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
    refusal_accuracy,
)
from lectureqa.schemas import Citation, ItemResult, RetrievedChunk


def _hit(chunk, score: float = 1.0) -> RetrievedChunk:
    return RetrievedChunk(chunk=chunk, score=score, support=0.8)


def test_retrieval_metrics(chunks) -> None:
    retrieved = [_hit(chunks[2]), _hit(chunks[1])]
    assert hit_at_k(retrieved, [2], ["lecture03_rag"])
    assert recall_at_k(retrieved, [2], ["lecture03_rag"]) == 1.0
    assert recall_at_k(retrieved, [9], ["lecture03_rag"]) == 0.0
    assert reciprocal_rank(retrieved, [3], ["lecture02_transformer"]) == 0.5
    assert reciprocal_rank(retrieved, [99], []) == 0.0


def test_citation_precision(chunks) -> None:
    citations = [
        Citation(doc_id="lecture03_rag", doc_title="RAG", page=2, chunk_id="a", snippet="x"),
        Citation(doc_id="lecture03_rag", doc_title="RAG", page=9, chunk_id="b", snippet="y"),
    ]
    assert citation_precision(citations, [2], ["lecture03_rag"]) == 0.5
    assert citation_precision([], [2], []) == 0.0


def _result(qid: str, kind: str, refused: bool, hit: bool, precision: float) -> ItemResult:
    return ItemResult(
        qid=qid,
        question="q",
        type=kind,  # type: ignore[arg-type]
        refused=refused,
        hit_at_k=hit,
        recall_at_k=1.0 if hit else 0.0,
        reciprocal_rank=1.0 if hit else 0.0,
        citation_precision=precision,
        grounded=precision > 0,
        answer="a",
        latency_ms=100,
    )


def test_aggregate_reports_expected_rates() -> None:
    results = [
        _result("q1", "answerable", False, True, 1.0),
        _result("q2", "answerable", False, False, 0.0),
        _result("q3", "unanswerable", True, False, 0.0),
    ]
    metrics = aggregate(results)
    assert metrics["hit_rate"] == 0.5
    assert metrics["n_answerable"] == 2.0
    assert metrics["unanswerable_refusal_rate"] == 1.0
    assert refusal_accuracy(results) == 1.0
    assert metrics["avg_latency_ms"] == 100.0
