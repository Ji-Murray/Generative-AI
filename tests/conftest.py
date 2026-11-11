from __future__ import annotations

from pathlib import Path

import pytest

from lectureqa.config import Settings
from lectureqa.retrieval.corpus import Corpus
from lectureqa.retrieval.embeddings import HashEmbedder
from lectureqa.retrieval.rerank import CoverageReranker
from lectureqa.retrieval.retriever import Retriever
from lectureqa.retrieval.store import LocalStore
from lectureqa.schemas import Chunk


def make_chunk(doc_id: str, page: int, index: int, text: str, title: str | None = None) -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}:p{page}:c{index}",
        doc_id=doc_id,
        doc_title=title or doc_id,
        page=page,
        chunk_index=index,
        text=text,
        char_start=0,
        char_end=len(text),
    )


SAMPLE_CHUNKS = [
    make_chunk(
        "lecture02_transformer",
        2,
        0,
        "缩放点积注意力公式为 softmax(QK^T / sqrt(d_k)) V。"
        "缩放因子 sqrt(d_k) 用于防止点积随维度增大而方差过大，导致 softmax 梯度消失。",
        "Transformer 架构",
    ),
    make_chunk(
        "lecture02_transformer",
        3,
        0,
        "多头注意力把 Q、K、V 投影到 h 个子空间并行计算，论文默认设置 h = 8 个注意力头，"
        "每个头的维度 d_k = d_model / h = 64。",
        "Transformer 架构",
    ),
    make_chunk(
        "lecture03_rag",
        2,
        0,
        "分块策略：chunk 大小建议 512 tokens，重叠 64 tokens。"
        "重叠过大导致检索冗余，过小则容易切断语义。",
        "RAG 概述",
    ),
    make_chunk(
        "lecture03_rag",
        4,
        0,
        "RAG 的生成侧指标包括引用精度 citation precision 与证据支持率，"
        "拒答能力需要单独评估。",
        "RAG 概述",
    ),
]


@pytest.fixture
def write_chunks():
    """把给定 chunks 写入 index_dir/chunks.jsonl，供 service 加载。"""
    return write_corpus


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        index_dir=tmp_path / "index",
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "uploads",
        learning_dir=tmp_path / "learning",
        store_backend="local",
        embedding_provider="hash",
        chunk_size=400,
        chunk_overlap=80,
        top_k=4,
        fetch_k=10,
        min_evidence_score=0.25,
        rerank="coverage",
        llm_api_key="test-key",
    )


@pytest.fixture
def chunks() -> list[Chunk]:
    return [chunk.model_copy(deep=True) for chunk in SAMPLE_CHUNKS]


def write_corpus(settings: Settings, chunks: list[Chunk]) -> None:
    import json

    settings.index_dir.mkdir(parents=True, exist_ok=True)
    with settings.chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")


@pytest.fixture
def corpus(chunks: list[Chunk]) -> Corpus:
    return Corpus(chunks)


@pytest.fixture
def retriever(settings: Settings, corpus: Corpus) -> Retriever:
    embedder = HashEmbedder(dim=settings.embedding_dim)
    store = LocalStore(settings.local_index_dir)
    store.reset()
    store.add(corpus.chunks, embedder.embed([chunk.text for chunk in corpus.chunks]))
    return Retriever(corpus, store, embedder, settings, CoverageReranker())
