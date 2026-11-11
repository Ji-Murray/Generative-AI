"""端到端回归：真实 PDF → 索引 → 问答 → Quiz → 评估报告，全部走同一条装配线。"""

from __future__ import annotations

import json

import pytest

from lectureqa.eval import runner
from lectureqa.ingest.pipeline import ingest
from lectureqa.llm import FakeLLM
from lectureqa.retrieval.embeddings import HashEmbedder
from lectureqa.retrieval.store import LocalStore
from lectureqa.service import LectureQAService

pytest.importorskip("pymupdf")

PAGES = [
    "RAG overview. Retrieval augmented generation reduces hallucination by grounding answers.",
    "Chunking: use 512 tokens per chunk with 64 tokens overlap for slide decks.",
    "Evaluation: recall at k and MRR for retrieval, citation precision for generation.",
]


def _make_pdf(path, pages: list[str]) -> None:
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz  # type: ignore[no-redef]

    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page()
            page.insert_textbox(fitz.Rect(56, 56, 540, 740), text, fontsize=12, lineheight=1.5)
        document.save(path)
    finally:
        document.close()


def test_full_pipeline(settings, tmp_path, monkeypatch) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _make_pdf(settings.data_dir / "lecture01_rag.pdf", PAGES)

    report = ingest(settings)
    assert report.documents == 1
    assert report.chunks >= 3

    doc_id = ""
    embedder = HashEmbedder(settings.embedding_dim)
    store = LocalStore(settings.local_index_dir)
    doc_id = LectureQAService(
        settings, llm=FakeLLM("NO_ANSWER"), embedder=embedder, store=store
    ).documents()[0].doc_id

    def responder(messages):
        content = messages[-1]["content"]
        if "输出 JSON 结构" in content:
            return json.dumps(
                {
                    "questions": [
                        {
                            "type": "true_false",
                            "difficulty": "easy",
                            "question": "The deck recommends 64 tokens of overlap.",
                            "options": ["True", "False"],
                            "answer": "True",
                            "explanation": "Page 2 states 64 tokens overlap.",
                            "sources": [{"doc_id": doc_id, "page": 2}],
                        }
                    ]
                }
            )
        return f"Use 512 tokens per chunk with 64 tokens of overlap [[{doc_id}:p2]]."

    service = LectureQAService(
        settings, llm=FakeLLM([""], handler=responder), embedder=embedder, store=store
    )

    answer = service.ask("What chunk size and overlap are recommended?")
    assert answer.grounded
    assert answer.citations[0].page == 2
    assert answer.citations[0].doc_id == doc_id

    quiz = service.quiz("chunking overlap", n=1)
    assert len(quiz.questions) == 1
    assert quiz.questions[0].answer == "True"

    testset = tmp_path / "testset.jsonl"
    rows = [
        {
            "qid": "e1",
            "question": "What chunk size and overlap are recommended?",
            "type": "answerable",
            "gold_doc_ids": [doc_id],
            "gold_pages": [2],
            "reference_answer": "512 tokens with 64 overlap.",
        },
        {
            "qid": "e2",
            "question": "How many GPUs does the lab cluster have?",
            "type": "unanswerable",
        },
    ]
    testset.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    monkeypatch.setattr(runner, "REPORT_DIR", tmp_path / "reports")

    eval_report = runner.run_evaluation(settings, testset, k=3, service=service)
    assert eval_report.metrics["hit_rate"] == 1.0
    assert eval_report.metrics["refusal_accuracy"] == 1.0
    assert (tmp_path / "reports").exists()
