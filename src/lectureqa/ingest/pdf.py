"""PDF → 页级文本抽取（保留页码，适配幻灯片式讲义）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lectureqa.textutils import normalize_ws

_HEADING_MAX_CHARS = 80
_SENTENCE_END = "。！？.!?:：;；"


class PDFError(RuntimeError):
    pass


@dataclass
class PageText:
    page: int
    text: str
    heading: str | None = None


@dataclass
class ParsedDocument:
    doc_id: str
    doc_title: str
    source_path: Path
    page_count: int
    pages: list[PageText] = field(default_factory=list)


def _guess_heading(page_text: str) -> str | None:
    """幻灯片首页行通常是标题：短、不含句末标点、非纯数字。"""
    for line in page_text.split("\n"):
        line = line.strip()
        if len(line) < 3:
            continue
        if len(line) <= _HEADING_MAX_CHARS and not set(line) & set(_SENTENCE_END):
            return re.sub(r"\s+", " ", line)
        return None
    return None


def extract_pages(
    path: Path, *, min_page_chars: int = 1
) -> tuple[str | None, list[PageText], int]:
    """抽取单份 PDF 的逐页文本。返回 (metadata 标题, 有文字的页列表, PDF 总页数)。"""
    try:
        import pymupdf as fitz  # PyMuPDF >= 1.24 推荐入口
    except ImportError:  # pragma: no cover - 老版本仅有 fitz 顶层包
        try:
            import fitz  # type: ignore[no-redef]
        except ImportError as exc:
            raise PDFError("缺少 PyMuPDF，请先 `pip install pymupdf`") from exc

    try:
        document = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 - PyMuPDF 抛的异常类型不稳定
        raise PDFError(f"无法打开 PDF {path.name}: {exc}") from exc

    try:
        meta_title = (document.metadata or {}).get("title") or None
        total_pages = int(document.page_count)
        pages: list[PageText] = []
        for index, page in enumerate(document, start=1):
            raw = page.get_text("text") or ""
            text = normalize_ws(raw)
            if len(text) < min_page_chars:
                continue
            pages.append(PageText(page=index, text=text, heading=_guess_heading(text)))
    finally:
        document.close()
    return meta_title, pages, total_pages


def parse_document(path: Path, *, min_page_chars: int = 1) -> ParsedDocument:
    from lectureqa.textutils import slugify

    meta_title, pages, total_pages = extract_pages(path, min_page_chars=min_page_chars)
    title = (meta_title or path.stem).strip() or path.stem
    return ParsedDocument(
        doc_id=slugify(path.stem),
        doc_title=title,
        source_path=path,
        page_count=total_pages or (pages[-1].page if pages else 0),
        pages=pages,
    )


def render_page_png(path: Path | str, page: int, *, dpi: int = 144) -> bytes:
    """把 PDF 的第 page 页（1-based）渲染成 PNG 字节，供前端预览与出处跳转。"""
    if page < 1:
        raise PDFError(f"页码必须从 1 开始，收到 {page}")
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        try:
            import fitz  # type: ignore[no-redef]
        except ImportError as exc:
            raise PDFError("缺少 PyMuPDF，请先 `pip install pymupdf`") from exc

    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise PDFError(f"找不到 PDF：{pdf_path}")

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise PDFError(f"无法打开 PDF {pdf_path.name}: {exc}") from exc

    try:
        if page > document.page_count:
            raise PDFError(f"{pdf_path.name} 只有 {document.page_count} 页，无法打开第 {page} 页")
        pixmap = document.load_page(page - 1).get_pixmap(dpi=dpi, alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()
