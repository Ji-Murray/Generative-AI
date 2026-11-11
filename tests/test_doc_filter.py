from __future__ import annotations

from lectureqa.retrieval.corpus import Corpus
from lectureqa.retrieval.embeddings import HashEmbedder
from lectureqa.retrieval.rerank import CoverageReranker
from lectureqa.retrieval.retriever import Retriever
from lectureqa.retrieval.store import LocalStore
from lectureqa.schemas import Chunk


def _chunk(doc_id: str, page: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}:p{page}:c0",
        doc_id=doc_id,
        doc_title=doc_id,
        page=page,
        chunk_index=0,
        text=text,
    )


def test_retrieve_never_leaks_other_lectures(settings) -> None:
    chunks = [
        _chunk("lecture2", 1, "Bayesian inference and neural network basics."),
        _chunk("lecture5", 1, "Diffusion models and flow matching for molecules."),
        _chunk("lecture02-transformer", 1, "Multi-head attention with eight heads."),
    ]
    corpus = Corpus(chunks)
    embedder = HashEmbedder(dim=settings.embedding_dim)
    store = LocalStore(settings.local_index_dir)
    store.reset()
    store.add(chunks, embedder.embed([chunk.text for chunk in chunks]))
    retriever = Retriever(corpus, store, embedder, settings, CoverageReranker())

    hits = retriever.retrieve("diffusion flow matching", doc_ids=["lecture5"], top_k=5)
    assert hits
    assert all(item.chunk.doc_id == "lecture5" for item in hits)

    hits = retriever.retrieve("attention heads", doc_ids=["lecture5"], top_k=5)
    assert all(item.chunk.doc_id == "lecture5" for item in hits)
