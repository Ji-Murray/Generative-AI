"""FastAPI 服务：把检索、问答、Quiz 能力暴露成 HTTP 接口，供前端与评估脚本复用。"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lectureqa.config import Settings, get_settings
from lectureqa.ingest.pipeline import IngestReport
from lectureqa.llm import LLMError
from lectureqa.schemas import (
    Answer,
    CourseOutline,
    DocumentInfo,
    LearningState,
    QuizResult,
    RetrievedChunk,
)
from lectureqa.service import LectureQAService

logger = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, description="用户问题")
    doc_ids: list[str] | None = Field(default=None, description="限定讲义范围，None 表示全部")
    top_k: int | None = Field(default=None, ge=1, le=20)
    allow_web: bool | None = Field(
        default=None,
        description="讲义证据不足时是否允许网络补充（结果会在 external_sources 中单独标注）",
    )


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    doc_ids: list[str] | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)


class ProgressUpdate(BaseModel):
    doc_id: str = Field(min_length=1)
    status: Literal["not_started", "learning", "completed"]


class QuizRequest(BaseModel):
    topic: str = Field(min_length=1)
    doc_ids: list[str] | None = None
    n: int = Field(default=5, ge=1, le=10)
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"
    types: list[Literal["mcq", "true_false", "short_answer"]] | None = None


class IngestRequest(BaseModel):
    paths: list[str] | None = Field(default=None, description="绝对路径列表；留空则扫描 DATA_DIR")
    reset: bool = True


def _service(request: Request) -> LectureQAService:
    service = request.app.state.service
    if service is None:
        service = LectureQAService(get_settings())
        request.app.state.service = service
    return service


def create_app(
    settings: Settings | None = None, service: LectureQAService | None = None
) -> FastAPI:
    app = FastAPI(
        title="LectureQA API",
        version="0.1.0",
        description="课程讲义智能问答：带出处的回答 + 可溯源 Quiz 生成",
    )
    app.state.service = service if service is not None else (
        LectureQAService(settings) if settings is not None else None
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health(svc: LectureQAService = Depends(_service)) -> dict:
        return svc.health()

    @app.get("/documents", response_model=list[DocumentInfo])
    def documents(svc: LectureQAService = Depends(_service)) -> list[DocumentInfo]:
        return svc.documents()

    @app.get("/outline", response_model=CourseOutline)
    def outline(
        refresh: bool = False, svc: LectureQAService = Depends(_service)
    ) -> CourseOutline:
        return svc.outline(refresh=refresh)

    @app.get("/progress", response_model=LearningState)
    def progress(svc: LectureQAService = Depends(_service)) -> LearningState:
        return svc.progress()

    @app.post("/progress", response_model=LearningState)
    def update_progress(
        payload: ProgressUpdate, svc: LectureQAService = Depends(_service)
    ) -> LearningState:
        return svc.set_lecture_status(payload.doc_id, payload.status)

    @app.post("/search", response_model=list[RetrievedChunk])
    def search(payload: SearchRequest, svc: LectureQAService = Depends(_service)) -> list[RetrievedChunk]:
        return svc.search(payload.query, doc_ids=payload.doc_ids, top_k=payload.top_k)

    @app.post("/ask", response_model=Answer)
    def ask(payload: AskRequest, svc: LectureQAService = Depends(_service)) -> Answer:
        try:
            return svc.ask(
                payload.question,
                doc_ids=payload.doc_ids,
                top_k=payload.top_k,
                allow_web=payload.allow_web,
            )
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/ask/stream")
    def ask_stream(payload: AskRequest, svc: LectureQAService = Depends(_service)) -> StreamingResponse:
        def event_stream() -> Iterator[str]:
            for event in svc.stream(
                payload.question,
                doc_ids=payload.doc_ids,
                top_k=payload.top_k,
                allow_web=payload.allow_web,
            ):
                yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/quiz", response_model=QuizResult)
    def quiz(payload: QuizRequest, svc: LectureQAService = Depends(_service)) -> QuizResult:
        try:
            return svc.quiz(
                payload.topic,
                doc_ids=payload.doc_ids,
                n=payload.n,
                difficulty=payload.difficulty,
                types=payload.types,
            )
        except LLMError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/ingest", response_model=IngestReport)
    def run_ingest(payload: IngestRequest, svc: LectureQAService = Depends(_service)) -> IngestReport:
        try:
            return svc.ingest(
                [Path(path) for path in payload.paths] if payload.paths else None,
                reset=payload.reset,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/ingest/upload", response_model=IngestReport)
    async def upload_ingest(
        files: list[UploadFile] = File(..., description="一个或多个 PDF 文件"),
        reset: bool = False,
        svc: LectureQAService = Depends(_service),
    ) -> IngestReport:
        settings = svc.settings
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        limit = settings.max_upload_mb * 1024 * 1024
        paths: list[Path] = []
        for file in files:
            name = Path(file.filename or "upload.pdf").name
            if not name.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail=f"{name}: 只支持 PDF 文件")
            data = await file.read()
            if len(data) > limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"{name}: 超过 {settings.max_upload_mb} MB 限制",
                )
            digest = hashlib.sha1(data).hexdigest()[:12]
            folder = settings.upload_dir / digest
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / name
            target.write_bytes(data)
            paths.append(target)
        try:
            return svc.ingest(paths, reset=reset)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()
