"""幻灯片感知分块：以「页」为不可跨越的边界，页内按句子打包 + 重叠。"""

from __future__ import annotations

from lectureqa.ingest.pdf import PageText, ParsedDocument
from lectureqa.schemas import Chunk
from lectureqa.textutils import normalize_ws, split_sentences


def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for sentence in split_sentences(text):
        index = text.find(sentence, cursor)
        if index < 0:
            index = cursor
        spans.append((index, index + len(sentence), sentence))
        cursor = index + len(sentence)
    return spans or [(0, len(text), text)]


def chunk_page(
    page: PageText,
    *,
    doc_id: str,
    doc_title: str,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
    min_chars: int = 40,
) -> list[Chunk]:
    """一页切成若干块；块不跨页，保证 [[doc:pN]] 这种引用精确到页。"""
    text = normalize_ws(page.text)
    if not text:
        return []

    spans = _sentence_spans(text)
    pieces: list[tuple[int, int]] = []
    index = 0
    total = len(spans)
    while index < total:
        start = index
        end = index
        length = 0
        while end < total and (length == 0 or length + len(spans[end][2]) + 1 <= chunk_size):
            length += len(spans[end][2]) + 1
            end += 1
        if end == start:  # 单句超长，独占一块
            end = start + 1
        pieces.append((start, end))

        if end >= total:
            break
        # 回退若干句做重叠，但必须前进至少一句，避免死循环
        back = end - 1
        overlap_chars = 0
        while back > start and overlap_chars < chunk_overlap:
            overlap_chars += len(spans[back][2]) + 1
            back -= 1
        index = max(back + 1, start + 1)

    chunks: list[Chunk] = []
    for start, end in pieces:
        char_start = spans[start][0]
        char_end = spans[end - 1][1]
        body = text[char_start:char_end].strip()
        if len(body) < min_chars and chunks:
            # 尾巴太短就并入上一块，避免产生碎片召回
            previous = chunks[-1]
            chunks[-1] = previous.model_copy(
                update={
                    "text": f"{previous.text}\n{body}".strip(),
                    "char_end": char_end,
                }
            )
            continue
        if not body:
            continue
        chunks.append(
            Chunk(
                chunk_id=f"{doc_id}:p{page.page}:c{len(chunks)}",
                doc_id=doc_id,
                doc_title=doc_title,
                page=page.page,
                chunk_index=len(chunks),
                text=body,
                char_start=char_start,
                char_end=char_end,
            )
        )
    return chunks


def chunk_document(
    document: ParsedDocument,
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
    min_chars: int = 40,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in document.pages:
        chunks.extend(
            chunk_page(
                page,
                doc_id=document.doc_id,
                doc_title=document.doc_title,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                min_chars=min_chars,
            )
        )
    return chunks
