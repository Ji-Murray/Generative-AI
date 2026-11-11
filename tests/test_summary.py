from __future__ import annotations

from lectureqa.generation.qa import Answerer, is_summary_query
from lectureqa.llm import FakeLLM
from lectureqa.retrieval.corpus import Corpus
from lectureqa.retrieval.embeddings import HashEmbedder
from lectureqa.retrieval.retriever import Retriever
from lectureqa.retrieval.store import LocalStore


def test_is_summary_query_detects_common_phrasings() -> None:
    assert is_summary_query("这讲了什么内容？")
    assert is_summary_query("帮我总结一下这门课")
    assert is_summary_query("课程概述")
    assert is_summary_query("你总结一下讲了什么")
    assert not is_summary_query("多头注意力默认使用多少个注意力头？")


def test_lecture_summary_prompt_asks_to_scan_slides(retriever, settings) -> None:
    llm = FakeLLM("本讲介绍扩散模型 [[lecture02_transformer:p2]]。")
    doc_id = next(iter(retriever.corpus.doc_ids()))
    answer = Answerer(retriever, llm, settings).answer(
        "你总结一下讲了什么", doc_ids=[doc_id]
    )
    assert answer.refused is False
    assert len(answer.evidence) >= 2
    pages = {item.chunk.page for item in answer.evidence}
    assert max(pages) > min(pages)
    # 走了单讲总结提示词
    system = llm.calls[0][0]["content"]
    assert "跨页" in system or "本讲" in system


def test_summary_uses_evidence_across_documents(retriever, settings) -> None:
    llm = FakeLLM(
        "课程涵盖 Transformer 与 RAG：前者讲注意力 [[lecture02_transformer:p2]]，"
        "后者讲分块 [[lecture03_rag:p2]]。"
    )
    answer = Answerer(retriever, llm, settings).answer("这讲了什么内容？")

    assert answer.refused is False
    assert answer.answer_scope == "lecture"
    assert answer.citations
    assert len({item.chunk.doc_id for item in answer.evidence}) >= 2
    assert not answer.external_sources


def test_summary_streams_and_cites(retriever, settings) -> None:
    llm = FakeLLM("课程讲了注意力 [[lecture02_transformer:p2]]。")
    events = list(Answerer(retriever, llm, settings).stream_answer("总结一下讲义"))

    assert events[-1].kind == "final"
    assert events[-1].answer is not None
    assert events[-1].answer.citations


def test_summary_with_empty_corpus_refuses(settings) -> None:
    corpus = Corpus([])
    embedder = HashEmbedder(dim=settings.embedding_dim)
    store = LocalStore(settings.local_index_dir)
    store.reset()
    retriever = Retriever(corpus, store, embedder, settings)
    llm = FakeLLM("不应被调用")

    answer = Answerer(retriever, llm, settings).answer("总结一下讲义")

    assert answer.refused is True
    assert llm.calls == []
