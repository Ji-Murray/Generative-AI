from __future__ import annotations

from lectureqa.ingest.chunker import chunk_page
from lectureqa.ingest.pdf import PageText
from lectureqa.textutils import content_tokens, split_sentences, tokenize


def test_tokenize_keeps_cjk_bigrams_and_latin_words() -> None:
    tokens = tokenize("RAG 的 chunk 大小是 512 tokens")
    assert "rag" in tokens
    assert "chunk" in tokens
    assert "512" in tokens
    assert "大小" in tokens
    assert "chunk大" not in tokens


def test_content_tokens_remove_stopwords() -> None:
    tokens = content_tokens("什么是 RAG")
    assert "rag" in tokens
    assert "什么" not in tokens


def test_split_sentences_handles_mixed_punctuation() -> None:
    text = "第一句话。第二句话！Is this a sentence? Yes."
    sentences = split_sentences(text)
    assert len(sentences) >= 3


def test_chunk_page_keeps_ids_unique_and_page_bound() -> None:
    page = PageText(page=7, text=("这是一个很长的句子，用来测试分块。" * 40))
    chunks = chunk_page(
        page,
        doc_id="lecture01",
        doc_title="概览",
        chunk_size=120,
        chunk_overlap=30,
        min_chars=10,
    )
    assert len(chunks) > 1
    assert {chunk.page for chunk in chunks} == {7}
    assert [chunk.chunk_id for chunk in chunks] == [
        f"lecture01:p7:c{index}" for index in range(len(chunks))
    ]
    assert all(chunk.text.strip() for chunk in chunks)


def test_short_page_yields_single_chunk() -> None:
    page = PageText(page=1, text="简短的一页讲义内容。")
    chunks = chunk_page(page, doc_id="d", doc_title="t", chunk_size=500, chunk_overlap=50)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "d:p1:c0"


def test_chunk_overlap_produces_shared_text() -> None:
    sentences = [f"第{i}句话讲了一个独立的知识点。" for i in range(12)]
    page = PageText(page=2, text="".join(sentences))
    chunks = chunk_page(
        page, doc_id="d", doc_title="t", chunk_size=60, chunk_overlap=25, min_chars=5
    )
    assert len(chunks) >= 3
    overlap_found = any(chunks[i].text[-10:] in chunks[i + 1].text for i in range(len(chunks) - 1))
    assert overlap_found
