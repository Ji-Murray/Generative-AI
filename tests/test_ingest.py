from __future__ import annotations

import json

import pytest

from lectureqa.ingest.pipeline import discover_pdfs, ingest, merge_corpus
from lectureqa.schemas import Chunk, DocumentInfo

pytest.importorskip("pymupdf")


def _make_pdf(path, pages: list[str], title: str | None = None) -> None:
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz  # type: ignore[no-redef]

    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page()
            page.insert_textbox(fitz.Rect(56, 56, 540, 740), text, fontsize=12, lineheight=1.5)
        if title:
            document.set_metadata({"title": title})
        document.save(path)
    finally:
        document.close()


def test_discover_pdfs_only_returns_pdf_files(tmp_path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "notes.txt").write_text("not a pdf", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "b.PDF").write_bytes(b"%PDF-1.4")
    found = {path.name for path in discover_pdfs(tmp_path)}
    assert found == {"a.pdf", "b.PDF"}


def test_ingest_builds_chunks_manifest_and_index(settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _make_pdf(
        settings.data_dir / "lecture01_overview.pdf",
        [
            "Course overview. Grading: project 40 percent, paper 20 percent, homework 40 percent.",
            "RAG pipeline: chunk size 512 tokens with overlap 64 tokens.",
        ],
        title="课程概览",
    )

    report = ingest(settings)

    assert report.documents == 1
    assert report.chunks >= 2
    assert report.embedded == report.chunks
    assert report.store_backend == "local"
    assert settings.chunks_path.exists()
    assert settings.manifest_path.exists()

    lines = [
        json.loads(line)
        for line in settings.chunks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {line["page"] for line in lines} == {1, 2}
    assert all(line["chunk_id"] == f"{line['doc_id']}:p{line['page']}:c{line['chunk_index']}" for line in lines)

    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    assert manifest["num_documents"] == 1
    assert manifest["documents"][0]["doc_title"] == "课程概览"


def test_ingest_raises_when_no_pdf_found(settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        ingest(settings)


def test_merge_corpus_replaces_same_doc_id() -> None:
    old_chunk = Chunk(
        chunk_id="lecture01:p1:c0",
        doc_id="lecture01",
        doc_title="旧讲义",
        page=1,
        chunk_index=0,
        text="old",
    )
    new_chunk = Chunk(
        chunk_id="lecture01:p2:c0",
        doc_id="lecture01",
        doc_title="新讲义",
        page=2,
        chunk_index=0,
        text="new",
    )
    other = Chunk(
        chunk_id="lecture02:p1:c0",
        doc_id="lecture02",
        doc_title="另一讲",
        page=1,
        chunk_index=0,
        text="other",
    )
    old_docs = [
        DocumentInfo(doc_id="lecture01", doc_title="旧讲义", source_path="", pages=1, chunks=1),
        DocumentInfo(doc_id="lecture02", doc_title="另一讲", source_path="", pages=1, chunks=1),
    ]
    new_docs = [
        DocumentInfo(doc_id="lecture01", doc_title="新讲义", source_path="upload.pdf", pages=2, chunks=1)
    ]

    chunks, documents = merge_corpus(
        [old_chunk, other], old_docs, [new_chunk], new_docs
    )

    assert {chunk.chunk_id for chunk in chunks} == {"lecture01:p2:c0", "lecture02:p1:c0"}
    assert {doc.doc_id: doc.doc_title for doc in documents} == {
        "lecture01": "新讲义",
        "lecture02": "另一讲",
    }


def test_incremental_ingest_keeps_existing_documents(settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _make_pdf(
        settings.data_dir / "lecture01_overview.pdf",
        ["Course overview and grading policy."],
        title="课程概览",
    )
    first = ingest(settings)
    assert first.documents == 1

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    uploaded = settings.upload_dir / "lecture02_rag.pdf"
    _make_pdf(
        uploaded,
        ["RAG pipeline: chunk size 512 tokens with overlap 64 tokens."],
        title="RAG 概述",
    )

    second = ingest(settings, paths=[uploaded], reset=False)

    assert second.documents == 2
    assert second.chunks >= 2
    manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["documents"]) == 2
    assert {item["doc_title"] for item in manifest["documents"]} == {"课程概览", "RAG 概述"}
