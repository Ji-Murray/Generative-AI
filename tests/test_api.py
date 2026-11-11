from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from lectureqa.api.main import create_app
from lectureqa.llm import FakeLLM
from lectureqa.retrieval.embeddings import HashEmbedder
from lectureqa.retrieval.store import LocalStore
from lectureqa.service import LectureQAService

QUIZ_JSON = json.dumps(
    {
        "questions": [
            {
                "type": "mcq",
                "difficulty": "easy",
                "question": "chunk 大小建议多少 tokens？",
                "options": ["512", "1024", "2048", "64"],
                "answer": "A",
                "explanation": "讲义写明 512 tokens。",
                "sources": [{"doc_id": "lecture03_rag", "page": 2}],
            }
        ]
    },
    ensure_ascii=False,
)


def _responder(messages) -> str:
    user_content = messages[-1]["content"]
    if "输出 JSON 结构" in user_content:
        return QUIZ_JSON
    return "分块建议 512 tokens，重叠 64 tokens [[lecture03_rag:p2]]。"


@pytest.fixture
def service(settings, chunks, write_chunks) -> LectureQAService:
    write_chunks(settings, chunks)
    embedder = HashEmbedder(settings.embedding_dim)
    store = LocalStore(settings.local_index_dir)
    store.reset()
    store.add(chunks, embedder.embed([chunk.text for chunk in chunks]))
    return LectureQAService(
        settings, llm=FakeLLM([""], handler=_responder), embedder=embedder, store=store
    )


@pytest.fixture
def client(service) -> TestClient:
    return TestClient(create_app(service=service))


def test_health_reports_index_state(client) -> None:
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["indexed"] is True
    assert payload["chunks"] == 4


def test_documents_lists_corpus(client) -> None:
    documents = client.get("/documents").json()
    assert {document["doc_id"] for document in documents} == {
        "lecture02_transformer",
        "lecture03_rag",
    }


def test_ask_returns_citations(client) -> None:
    response = client.post("/ask", json={"question": "分块大小和重叠是多少？"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["refused"] is False
    assert payload["citations"][0]["page"] == 2
    assert payload["citations"][0]["doc_id"] == "lecture03_rag"


def test_ask_stream_emits_sse_events(client) -> None:
    with client.stream(
        "POST", "/ask/stream", json={"question": "分块大小和重叠是多少？"}
    ) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert '"kind": "delta"' in body
    assert '"kind": "final"' in body
    assert "[DONE]" in body


def test_quiz_endpoint_returns_grounded_questions(client) -> None:
    response = client.post("/quiz", json={"topic": "分块策略", "n": 1})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["questions"]) == 1
    assert payload["questions"][0]["sources"][0]["doc_id"] == "lecture03_rag"


def test_ingest_without_pdfs_returns_400(client) -> None:
    response = client.post("/ingest", json={})
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]
