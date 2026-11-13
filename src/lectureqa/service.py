"""服务门面：API / CLI / Streamlit 共用同一条装配线，避免各处重复拼装。"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

from lectureqa.config import Settings, get_settings
from lectureqa.generation.qa import Answerer
from lectureqa.generation.quiz import QuizGenerator
from lectureqa.ingest.pipeline import IngestReport, ingest
from lectureqa.learning.outline import build_outline
from lectureqa.learning.progress import ProgressStore
from lectureqa.llm import LLM, LLMClient
from lectureqa.retrieval.corpus import Corpus
from lectureqa.retrieval.embeddings import make_embedder
from lectureqa.retrieval.rerank import make_reranker
from lectureqa.retrieval.retriever import Retriever
from lectureqa.retrieval.store import make_store
from lectureqa.retrieval.web import make_web_search
from lectureqa.schemas import (
    Answer,
    CourseOutline,
    DocumentInfo,
    LearningState,
    QuizResult,
    RetrievedChunk,
    StreamEvent,
)

logger = logging.getLogger(__name__)


class LectureQAService:
    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLM | None = None,
        *,
        embedder=None,
        store=None,
        web_search=None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm: LLM = llm or LLMClient(self.settings)
        self.corpus = Corpus.load(self.settings.chunks_path)
        self.embedder = embedder or make_embedder(self.settings)
        self.store = store if store is not None else make_store(self.settings)
        self.web_search = web_search if web_search is not None else make_web_search(self.settings)
        self.retriever = Retriever(
            self.corpus, self.store, self.embedder, self.settings, make_reranker(self.settings)
        )
        self.answerer = Answerer(
            self.retriever, self.llm, self.settings, web_search=self.web_search
        )
        self.quiz_generator = QuizGenerator(self.retriever, self.llm, self.settings)
        self.progress_store = ProgressStore(self.settings)

    # ------------------------------------------------------------------ 索引
    @property
    def indexed(self) -> bool:
        return len(self.corpus) > 0

    @property
    def manifest(self) -> dict:
        path = self.settings.manifest_path
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def documents(self) -> list[DocumentInfo]:
        from lectureqa.learning.outline import order_documents

        raw = self.manifest.get("documents")
        if isinstance(raw, list):
            documents = [DocumentInfo.model_validate(item) for item in raw]
        else:
            documents = self.corpus.documents()
        return order_documents(documents)

    def ingest(self, paths: list[Path] | None = None, *, reset: bool = True) -> IngestReport:
        report = ingest(self.settings, paths=paths, reset=reset)
        self.reload()
        return report

    def reload(self) -> None:
        self.corpus = Corpus.load(self.settings.chunks_path)
        self.store = make_store(self.settings)
        self.web_search = make_web_search(self.settings)
        self.retriever = Retriever(
            self.corpus, self.store, self.embedder, self.settings, make_reranker(self.settings)
        )
        self.answerer = Answerer(
            self.retriever, self.llm, self.settings, web_search=self.web_search
        )
        self.quiz_generator = QuizGenerator(self.retriever, self.llm, self.settings)

    def set_web_fallback(self, enabled: bool) -> None:
        """让前端的显式来源选择即时启用或关闭 Wikipedia 补充。"""
        mode = "wikipedia" if enabled else "off"
        if self.settings.web_fallback == mode and (
            enabled or self.web_search.name == "off"
        ):
            return
        self.settings = self.settings.model_copy(update={"web_fallback": mode})
        self.web_search = make_web_search(self.settings)
        self.answerer = Answerer(
            self.retriever, self.llm, self.settings, web_search=self.web_search
        )

    # ------------------------------------------------------------------ 能力
    def search(
        self,
        query: str,
        *,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        # Retriever 内自动对中文术语做英文化扩写
        return self.retriever.retrieve(query, doc_ids=doc_ids, top_k=top_k)

    def ask(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
        allow_web: bool | None = None,
    ) -> Answer:
        if allow_web is not None:
            self.set_web_fallback(allow_web)
        return self.answerer.answer(
            question, doc_ids=doc_ids, top_k=top_k, allow_web=allow_web
        )

    def stream(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
        allow_web: bool | None = None,
    ) -> Iterator[StreamEvent]:
        if allow_web is not None:
            self.set_web_fallback(allow_web)
        return self.answerer.stream_answer(
            question, doc_ids=doc_ids, top_k=top_k, allow_web=allow_web
        )

    def quiz(
        self,
        topic: str,
        *,
        doc_ids: list[str] | None = None,
        n: int = 5,
        difficulty: str = "mixed",
        types: list[str] | None = None,
        on_progress=None,
    ) -> QuizResult:
        return self.quiz_generator.generate(
            topic,
            doc_ids=doc_ids,
            n=n,
            difficulty=difficulty,
            types=types,
            on_progress=on_progress,
        )

    # ------------------------------------------------------------------ 学习
    def outline(self, *, refresh: bool = False) -> CourseOutline:
        """课程地图：整门课总览 + 逐讲学习卡片，结果缓存到 var/learning/outline.json。"""
        return build_outline(
            self.settings, self.llm, self.corpus, self.documents(), refresh=refresh
        )

    def page_image(self, doc_id: str, page: int, *, dpi: int = 144) -> bytes | None:
        """渲染指定讲义 PDF 页为 PNG；找不到文件或页码越界时返回 None。"""
        from lectureqa.ingest.pdf import PDFError, render_page_png

        document = next((item for item in self.documents() if item.doc_id == doc_id), None)
        if document is None or not document.source_path:
            return None
        try:
            return render_page_png(document.source_path, page, dpi=dpi)
        except PDFError as exc:
            logger.warning("page_image failed for %s p.%s: %s", doc_id, page, exc)
            return None

    def progress(self) -> LearningState:
        return self.progress_store.load()

    def set_lecture_status(self, doc_id: str, status: str) -> LearningState:
        return self.progress_store.set_status(doc_id, status)  # type: ignore[arg-type]

    def touch_lecture(self, doc_id: str) -> LearningState:
        return self.progress_store.touch(doc_id)

    def record_quiz(self, doc_id: str, *, correct: int, total: int) -> LearningState:
        return self.progress_store.record_quiz(doc_id, correct=correct, total=total)

    def record_quiz_attempt(self, attempt) -> LearningState:
        return self.progress_store.record_attempt(attempt)

    def wrong_attempts(self, lecture_id: str | None = None, *, limit: int = 50):
        return self.progress_store.wrong_attempts(lecture_id, limit=limit)

    def weak_points(self, *, limit: int = 12):
        return self.progress_store.weak_points(limit=limit)

    def recent_lecture_id(self) -> str | None:
        return self.progress_store.recent_lecture_id()

    def health(self) -> dict:
        return {
            "status": "ok",
            "indexed": self.indexed,
            "chunks": len(self.corpus),
            "documents": len(self.documents()),
            "store_backend": self.store.backend,
            "embedder": self.embedder.name,
            "web_backend": self.web_search.name,
            "llm_model": self.llm.model,
            "llm_configured": self.settings.llm_configured,
            "index_dir": str(self.settings.index_dir),
        }
