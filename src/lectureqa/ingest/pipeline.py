"""数据管线：data/*.pdf → 页级文本 → 分块 → chunks.jsonl → 向量索引 + manifest。"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from lectureqa.config import Settings
from lectureqa.ingest.chunker import chunk_document
from lectureqa.ingest.pdf import PDFError, parse_document
from lectureqa.retrieval.corpus import Corpus
from lectureqa.retrieval.embeddings import make_embedder
from lectureqa.retrieval.store import make_store
from lectureqa.schemas import Chunk, DocumentInfo

logger = logging.getLogger(__name__)


class IngestReport(BaseModel):
    documents: int
    pages: int
    chunks: int
    embedded: int
    store_backend: str
    embedder: str
    index_dir: str
    elapsed_ms: int
    skipped: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def discover_pdfs(data_dir: Path) -> list[Path]:
    if not data_dir.exists():
        return []
    return sorted(
        path
        for path in data_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf" and not path.name.startswith(".")
    )


def discover_all_pdfs(settings: Settings) -> list[Path]:
    """默认扫描 data/ 与上传目录，避免把讲义位置写死；同一份文件只保留一次。"""
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    paths: list[Path] = []
    for directory in (settings.data_dir, settings.upload_dir):
        for path in discover_pdfs(directory):
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            try:
                digest = hashlib.sha1(path.read_bytes()).hexdigest()
            except OSError:
                continue
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            paths.append(path)
    return paths


def merge_corpus(
    existing_chunks: list[Chunk],
    existing_documents: list[DocumentInfo],
    new_chunks: list[Chunk],
    new_documents: list[DocumentInfo],
) -> tuple[list[Chunk], list[DocumentInfo]]:
    """增量导入：同名 doc_id 以新上传文件为准，其余讲义保留。"""
    replaced = {document.doc_id for document in new_documents}
    kept_chunks = [chunk for chunk in existing_chunks if chunk.doc_id not in replaced]
    kept_documents = [
        document for document in existing_documents if document.doc_id not in replaced
    ]

    seen_chunks: set[str] = set()
    chunks: list[Chunk] = []
    for chunk in [*kept_chunks, *new_chunks]:
        if chunk.chunk_id in seen_chunks:
            continue
        seen_chunks.add(chunk.chunk_id)
        chunks.append(chunk)

    seen_docs: set[str] = set()
    documents: list[DocumentInfo] = []
    for document in [*kept_documents, *new_documents]:
        if document.doc_id in seen_docs:
            continue
        seen_docs.add(document.doc_id)
        documents.append(document)
    return chunks, documents


def _load_existing(settings: Settings) -> tuple[list[Chunk], list[DocumentInfo]]:
    chunks = Corpus.load(settings.chunks_path).chunks
    if settings.manifest_path.exists():
        try:
            manifest = json.loads(settings.manifest_path.read_text(encoding="utf-8"))
            documents = [
                DocumentInfo.model_validate(item) for item in manifest.get("documents", [])
            ]
            if documents:
                return chunks, documents
        except (json.JSONDecodeError, ValueError):
            logger.warning("manifest.json 读取失败，改为从分块推导讲义清单")

    grouped: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.doc_id, []).append(chunk)
    documents = [
        DocumentInfo(
            doc_id=doc_id,
            doc_title=items[0].doc_title,
            source_path="",
            pages=max(chunk.page for chunk in items),
            chunks=len(items),
        )
        for doc_id, items in grouped.items()
    ]
    return chunks, documents


def build_chunks(
    paths: list[Path], settings: Settings
) -> tuple[list[Chunk], list[DocumentInfo], list[str], int]:
    chunks: list[Chunk] = []
    documents: list[DocumentInfo] = []
    skipped: list[str] = []
    page_total = 0
    used_ids: set[str] = set()

    for path in paths:
        if not path.is_file():
            skipped.append(f"{path.name}: 不是文件")
            continue
        try:
            parsed = parse_document(path)
        except (PDFError, OSError) as exc:
            logger.warning("跳过 %s: %s", path.name, exc)
            skipped.append(f"{path.name}: {exc}")
            continue

        base_id = parsed.doc_id
        suffix = 2
        while parsed.doc_id in used_ids:
            parsed.doc_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(parsed.doc_id)

        doc_chunks = chunk_document(
            parsed,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            min_chars=settings.min_chunk_chars,
        )
        if not doc_chunks:
            skipped.append(f"{path.name}: 未抽取到可用文本（可能是扫描版 PDF）")
            continue

        chunks.extend(doc_chunks)
        page_total += parsed.page_count
        documents.append(
            DocumentInfo(
                doc_id=parsed.doc_id,
                doc_title=parsed.doc_title,
                source_path=str(path),
                pages=parsed.page_count,
                chunks=len(doc_chunks),
            )
        )
    return chunks, documents, skipped, page_total


def _write_chunks(chunks: list[Chunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")


def _write_manifest(
    settings: Settings,
    documents: list[DocumentInfo],
    chunks: list[Chunk],
    embedder_name: str,
    store_backend: str,
) -> None:
    manifest = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "store_backend": store_backend,
        "embedder": embedder_name,
        "embedding_provider": settings.embedding_provider,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "num_documents": len(documents),
        "num_chunks": len(chunks),
        "documents": [document.model_dump() for document in documents],
    }
    settings.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    settings.manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def ingest(
    settings: Settings,
    *,
    paths: list[Path] | None = None,
    reset: bool = True,
) -> IngestReport:
    started = time.perf_counter()
    pdf_paths = paths if paths is not None else discover_all_pdfs(settings)
    if not pdf_paths:
        raise FileNotFoundError(
            f"在 {settings.data_dir} 或 {settings.upload_dir} 下没有找到 PDF"
        )

    new_chunks, new_documents, skipped, _new_pages = build_chunks(pdf_paths, settings)
    if not new_chunks:
        raise ValueError("没有产出任何分块，请检查 PDF 是否为可提取文本的版本")

    if reset:
        chunks, documents = new_chunks, new_documents
    else:
        existing_chunks, existing_documents = _load_existing(settings)
        chunks, documents = merge_corpus(
            existing_chunks, existing_documents, new_chunks, new_documents
        )
    page_total = sum(document.pages for document in documents)

    _write_chunks(chunks, settings.chunks_path)
    settings.index_dir.mkdir(parents=True, exist_ok=True)

    embedder = make_embedder(settings)
    store = make_store(settings)
    store.reset()

    notes: list[str] = []
    embedded = 0
    try:
        vectors = embedder.embed([chunk.text for chunk in chunks])
        store.add(chunks, vectors)
        embedded = len(vectors)
    except Exception as exc:  # noqa: BLE001 - 无 Key/断网时仍保留词面检索能力
        logger.warning("向量化失败（%s），仅保留 BM25 词面检索", exc)
        notes.append(f"向量化失败，已跳过向量索引：{exc}")

    _write_manifest(settings, documents, chunks, embedder.name, store.backend)

    return IngestReport(
        documents=len(documents),
        pages=page_total,
        chunks=len(chunks),
        embedded=embedded,
        store_backend=store.backend,
        embedder=embedder.name,
        index_dir=str(settings.index_dir),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        skipped=skipped,
        notes=notes,
    )
