from __future__ import annotations

from lectureqa.generation.qa import (
    build_citations,
    display_answer,
    parse_markers,
    strip_invalid_markers,
)
from lectureqa.schemas import RetrievedChunk


def _retrieved(chunks) -> list[RetrievedChunk]:
    return [RetrievedChunk(chunk=chunk, score=1.0, support=0.9) for chunk in chunks]


def test_parse_markers_accepts_spaces_and_p_prefix() -> None:
    text = "结论一 [[lecture02_transformer:p2]]，结论二 [[ lecture03_rag : p 4 ]]"
    assert parse_markers(text) == [("lecture02_transformer", 2), ("lecture03_rag", 4)]


def test_parse_markers_accepts_missing_p_prefix() -> None:
    text = "结论一 [[lecture02_transformer:2]]，结论二 [[lecture03_rag:4]]"
    assert parse_markers(text) == [("lecture02_transformer", 2), ("lecture03_rag", 4)]


def test_parse_markers_accepts_literal_doc_id_prefix() -> None:
    text = "FM [[doc_id:lecture5:p67]]，转折点 [[doc_id=lecture5:p72]]"
    assert parse_markers(text) == [("lecture5", 67), ("lecture5", 72)]


def test_strip_invalid_markers_removes_fabricated_citations() -> None:
    cleaned, invalid = strip_invalid_markers(
        "有据可查 [[lecture02_transformer:p2]]，无中生有 [[lecture09_fake:p99]]",
        {("lecture02_transformer", 2)},
    )
    assert "[[lecture02_transformer:p2]]" in cleaned
    assert "lecture09_fake" not in cleaned
    assert invalid == ["[[lecture09_fake:p99]]"]


def test_strip_invalid_markers_normalizes_literal_doc_id_prefix() -> None:
    cleaned, invalid = strip_invalid_markers(
        "建模 [[doc_id:lecture5:p67]]，编造 [[doc_id:lecture5:p999]]",
        {("lecture5", 67)},
    )
    assert cleaned == "建模 [[lecture5:p67]]，编造"
    assert invalid == ["[[doc_id:lecture5:p999]]"]


def test_display_answer_replaces_markers_with_page_chips() -> None:
    text = "流匹配 [[lecture5:p67]]。虚拟细胞 [[web:2]]"
    assert display_answer(text) == "流匹配 〔p.67〕。虚拟细胞 〔网2〕"


def test_build_citations_dedupes_and_orders(chunks) -> None:
    evidence = _retrieved(chunks)
    citations = build_citations(
        [("lecture03_rag", 2), ("lecture02_transformer", 3), ("lecture03_rag", 2)], evidence
    )
    assert [citation.chunk_id for citation in citations] == [
        "lecture03_rag:p2:c0",
        "lecture02_transformer:p3:c0",
    ]
    assert citations[0].doc_title == "RAG 概述"
    assert citations[0].snippet


def test_build_citations_ignores_unknown_pages(chunks) -> None:
    evidence = _retrieved(chunks)
    assert build_citations([("lecture03_rag", 99)], evidence) == []
