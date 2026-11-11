from __future__ import annotations

from lectureqa.retrieval.bm25 import BM25Index
from lectureqa.retrieval.rerank import coverage_score


def test_bm25_prefers_the_matching_document() -> None:
    index = BM25Index(
        [
            "缩放点积注意力使用 sqrt(d_k) 做缩放",
            "分块大小 512 tokens，重叠 64 tokens",
            "位置编码注入序列顺序信息",
        ]
    )
    hits = index.search("分块重叠是多少", k=2)
    assert hits
    assert hits[0][0] == 1


def test_bm25_respects_allowed_positions() -> None:
    index = BM25Index(["tokens 分块", "tokens 重叠", "tokens 编码"])
    hits = index.search("tokens", k=3, allowed={2})
    assert [position for position, _ in hits] == [2]


def test_retriever_returns_page_level_evidence(retriever) -> None:
    results = retriever.retrieve("chunk 大小和 overlap 建议是多少？")
    assert results
    assert results[0].chunk.doc_id == "lecture03_rag"
    assert results[0].chunk.page == 2
    assert results[0].support > 0


def test_retriever_filters_by_doc_id(retriever) -> None:
    results = retriever.retrieve("多头注意力多少个头", doc_ids=["lecture02_transformer"])
    assert results
    assert {item.chunk.doc_id for item in results} == {"lecture02_transformer"}
    assert retriever.retrieve("分块重叠", doc_ids=["lecture02_transformer"]) == []


def test_retriever_returns_empty_for_offtopic_query(retriever) -> None:
    assert retriever.retrieve("量子退火与拓扑绝缘体") == []


def test_coverage_score_is_bounded() -> None:
    assert coverage_score("多头注意力", "论文默认 h = 8 个注意力头，多头并行") > 0.3
    assert coverage_score("量子退火", "多头注意力默认八个头") == 0.0
    score = coverage_score("注意力", "注意力")
    assert 0.0 <= score <= 1.0


def test_openai_embedder_uses_configured_batch_size(settings) -> None:
    from lectureqa.retrieval.embeddings import OpenAIEmbedder

    embedder = OpenAIEmbedder(settings.model_copy(update={"embedding_batch_size": 7}))
    assert embedder.batch_size == 7


def test_summary_evidence_covers_every_document(retriever) -> None:
    results = retriever.summary_evidence("这门课程讲了什么")
    covered = {item.chunk.doc_id for item in results}
    assert covered == set(retriever.corpus.doc_ids())


def test_summary_evidence_scans_beyond_first_page(retriever) -> None:
    doc_id = next(iter(retriever.corpus.doc_ids()))
    results = retriever.summary_evidence("总结一下本讲讲了什么", doc_ids=[doc_id])
    assert results
    pages = {item.chunk.page for item in results}
    # 单讲总结必须跨页，不能只停在封面
    assert len(results) >= 2
    assert max(pages) > min(pages)
