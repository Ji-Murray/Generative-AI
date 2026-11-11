from __future__ import annotations

from pathlib import Path

import pytest

from lectureqa.ingest.pdf import PDFError, render_page_png

pytest.importorskip("pymupdf")


def _make_pdf(path: Path, pages: list[str]) -> None:
    import pymupdf as fitz

    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page()
            page.insert_textbox(fitz.Rect(56, 56, 540, 740), text, fontsize=14)
        document.save(path)
    finally:
        document.close()


def test_render_page_png_returns_png_bytes(tmp_path: Path) -> None:
    path = tmp_path / "deck.pdf"
    _make_pdf(path, ["第一页 Attention", "第二页 RAG"])
    png = render_page_png(path, 2, dpi=72)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 200


def test_render_page_png_rejects_bad_page(tmp_path: Path) -> None:
    path = tmp_path / "deck.pdf"
    _make_pdf(path, ["only one page"])
    with pytest.raises(PDFError):
        render_page_png(path, 0)
    with pytest.raises(PDFError):
        render_page_png(path, 9)


def test_service_page_image(settings, tmp_path: Path) -> None:
    from lectureqa.schemas import DocumentInfo
    from lectureqa.service import LectureQAService

    path = tmp_path / "lecture.pdf"
    _make_pdf(path, ["slide one", "slide two"])
    service = LectureQAService(settings)
    service.documents = lambda: [  # type: ignore[method-assign]
        DocumentInfo(
            doc_id="lecture",
            doc_title="Demo",
            source_path=str(path),
            pages=2,
            chunks=2,
        )
    ]
    assert service.page_image("lecture", 1) is not None
    assert service.page_image("missing", 1) is None
    assert service.page_image("lecture", 99) is None
