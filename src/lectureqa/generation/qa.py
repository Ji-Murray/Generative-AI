"""问答：检索 → 证据充分性判定 → 带引用生成 → 引用校验。"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Iterator

from lectureqa.config import Settings
from lectureqa.generation import prompts
from lectureqa.llm import LLM, LLMError, format_llm_error
from lectureqa.retrieval.retriever import Retriever
from lectureqa.retrieval.web import WebSearch
from lectureqa.schemas import Answer, Citation, ExternalSource, RetrievedChunk, StreamEvent
from lectureqa.textutils import has_cjk, truncate

# 兼容模型常见变体：[[lecture5:p67]] / [[doc_id=lecture5:p67]] / [[doc_id:lecture5:p67]]
# 明确排除 [[web:N]]，避免把网络引用误当成讲义页码。
MARKER_RE = re.compile(
    r"\[\[\s*(?:doc_id\s*[=:]\s*)?(?!web\s*:)([^\[\]\s:=]+)\s*:\s*p?\s*(\d+)\s*\]\]",
    re.IGNORECASE,
)
WEB_MARKER_RE = re.compile(r"\[\[\s*web\s*:\s*(\d+)\s*\]\]", re.IGNORECASE)
# 外部补充模式下要剔除的讲义引用：与 MARKER_RE 同形，语义上强调“删讲义标记”
LECTURE_MARKER_RE = MARKER_RE
SUMMARY_RE = re.compile(
    r"(总结|概括|概述|总览|大纲|目录|讲了什么|讲什么|讲的内容|内容有哪些|课程内容|这门课|本讲|这讲|介绍一下)"
)


def is_summary_query(text: str) -> bool:
    return bool(SUMMARY_RE.search(text or ""))

REFUSAL_ZH = (
    "讲义中没有找到足以支撑这个问题的内容，因此我不作答。"
    "可以换个问法、补充关键词，或指明相关讲义与章节。"
)
REFUSAL_EN = (
    "The lecture materials do not contain enough evidence to answer this question, "
    "so I will not guess. Try rephrasing or pointing to the relevant lecture/section."
)


def parse_markers(text: str) -> list[tuple[str, int]]:
    return [(match.group(1), int(match.group(2))) for match in MARKER_RE.finditer(text)]


def evidence_keys(chunks: list[RetrievedChunk]) -> set[tuple[str, int]]:
    return {(item.chunk.doc_id, item.chunk.page) for item in chunks}


def strip_invalid_markers(text: str, valid: set[tuple[str, int]]) -> tuple[str, list[str]]:
    """校验引用：有效标记规范成 [[doc_id:pN]]，编造的删掉并返回。"""
    invalid: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        key = (match.group(1), int(match.group(2)))
        if key in valid:
            return f"[[{key[0]}:p{key[1]}]]"
        invalid.append(match.group(0))
        return ""

    cleaned = MARKER_RE.sub(_replace, text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip(), invalid


def display_answer(text: str) -> str:
    """前端展示用：把 [[doc_id:pN]] / [[web:N]] 换成可读的 〔p.N〕 / 〔网N〕。"""
    rendered = MARKER_RE.sub(lambda match: f"〔p.{int(match.group(2))}〕", text or "")
    return WEB_MARKER_RE.sub(lambda match: f"〔网{int(match.group(1))}〕", rendered)


def parse_web_markers(text: str) -> list[int]:
    return [int(match.group(1)) for match in WEB_MARKER_RE.finditer(text)]


def strip_invalid_web_markers(text: str, valid: set[int]) -> tuple[str, list[str]]:
    """校验 [[web:N]] 的编号是否落在本次网络结果范围内，越界的删掉并记录。"""
    invalid: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        if int(match.group(1)) in valid:
            return match.group(0)
        invalid.append(match.group(0))
        return ""

    cleaned = WEB_MARKER_RE.sub(_replace, text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip(), invalid


def strip_lecture_markers(text: str) -> tuple[str, list[str]]:
    """外部补充模式下，讲义引用未经证据校验，必须全部剔除。"""
    removed = [match.group(0) for match in LECTURE_MARKER_RE.finditer(text)]
    if not removed:
        return text, []
    cleaned = LECTURE_MARKER_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned.strip(), removed


def build_citations(
    markers: list[tuple[str, int]], evidence: list[RetrievedChunk]
) -> list[Citation]:
    """把有效标记映射成引用；未落在本次证据里的页码不会产生引用。"""
    index: dict[tuple[str, int], RetrievedChunk] = {}
    for item in evidence:
        index.setdefault((item.chunk.doc_id, item.chunk.page), item)
    citations: list[Citation] = []
    seen: set[tuple[str, int]] = set()
    for doc_id, page in markers:
        key = (doc_id, page)
        if key in seen or key not in index:
            continue
        seen.add(key)
        chunk = index[key].chunk
        citations.append(
            Citation(
                doc_id=doc_id,
                doc_title=chunk.doc_title,
                page=page,
                chunk_id=chunk.chunk_id,
                snippet=truncate(chunk.text, 300),
            )
        )
    return citations


def refusal_text(question: str) -> str:
    return REFUSAL_ZH if has_cjk(question) else REFUSAL_EN


class Answerer:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLM,
        settings: Settings,
        web_search: WebSearch | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm
        self.settings = settings
        self.web_search = web_search

    # ------------------------------------------------------------------ 内部
    def _retrieve(
        self, question: str, doc_ids: list[str] | None, top_k: int | None
    ) -> tuple[list[RetrievedChunk], float]:
        # Retriever 内会对中文做术语表英文化扩写；此处保留原问题供生成用
        evidence = self.retriever.retrieve(question, doc_ids=doc_ids, top_k=top_k)
        return evidence, self.retriever.best_support(evidence)

    def _summary_evidence(
        self, question: str, doc_ids: list[str] | None
    ) -> list[RetrievedChunk]:
        return self.retriever.summary_evidence(question, doc_ids=doc_ids)

    def _messages(self, question: str, evidence: list[RetrievedChunk]) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": prompts.qa_system_prompt(self.settings.default_language)},
            {
                "role": "user",
                "content": prompts.QA_USER.format(
                    evidence=prompts.format_evidence(evidence), question=question
                ),
            },
        ]

    def _summary_messages(
        self, question: str, evidence: list[RetrievedChunk]
    ) -> list[dict[str, str]]:
        single = len({item.chunk.doc_id for item in evidence}) <= 1
        user_template = prompts.LECTURE_SUMMARY_USER if single else prompts.SUMMARY_USER
        return [
            {
                "role": "system",
                "content": prompts.summary_system_prompt(
                    self.settings.default_language, single_lecture=single
                ),
            },
            {
                "role": "user",
                "content": user_template.format(
                    evidence=prompts.format_evidence(evidence), question=question
                ),
            },
        ]

    def _external_messages(
        self, question: str, sources: list[ExternalSource]
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": prompts.external_system_prompt(self.settings.default_language),
            },
            {
                "role": "user",
                "content": prompts.EXTERNAL_USER.format(
                    web_results=prompts.format_external_sources(sources), question=question
                ),
            },
        ]

    def _web_allowed(self, allow_web: bool | None) -> bool:
        if allow_web is None:
            return self.settings.web_fallback != "off"
        return allow_web

    def _search_web(self, question: str, allow_web: bool | None) -> list[ExternalSource]:
        if not self.web_search or not self._web_allowed(allow_web):
            return []
        return self.web_search.search(question, self.settings.web_max_results)

    def _refusal(self, question: str, evidence: list[RetrievedChunk], started: float) -> Answer:
        return Answer(
            question=question,
            answer=refusal_text(question),
            citations=[],
            evidence=evidence,
            grounded=False,
            refused=True,
            answer_scope="none",
            model=self.llm.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _finalize(
        self, question: str, raw: str, evidence: list[RetrievedChunk], started: float
    ) -> Answer:
        text = (raw or "").strip()
        if not text or text.upper().startswith(prompts.NO_ANSWER):
            return self._refusal(question, evidence, started)

        valid_keys = evidence_keys(evidence)
        cleaned, invalid = strip_invalid_markers(text, valid_keys)
        citations = build_citations(parse_markers(cleaned), evidence)
        return Answer(
            question=question,
            answer=cleaned,
            citations=citations,
            evidence=evidence,
            grounded=bool(citations),
            refused=False,
            invalid_citations=invalid,
            answer_scope="lecture",
            model=self.llm.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _finalize_external(
        self,
        question: str,
        raw: str,
        evidence: list[RetrievedChunk],
        sources: list[ExternalSource],
        started: float,
    ) -> Answer:
        text = (raw or "").strip()
        if not text or text.upper().startswith(prompts.NO_ANSWER):
            return self._refusal(question, evidence, started)

        cleaned, invalid_web = strip_invalid_web_markers(text, set(range(1, len(sources) + 1)))
        cleaned, invalid_lecture = strip_lecture_markers(cleaned)
        used = sorted(set(parse_web_markers(cleaned)))
        if not used:
            return self._refusal(question, evidence, started)

        return Answer(
            question=question,
            answer=cleaned,
            citations=[],
            evidence=evidence,
            external_sources=[sources[index - 1] for index in used],
            grounded=False,
            refused=False,
            invalid_citations=[*invalid_web, *invalid_lecture],
            answer_scope="external",
            model=self.llm.model,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _messages_for(
        self, question: str, evidence: list[RetrievedChunk], summary: bool
    ) -> list[dict[str, str]]:
        if summary:
            return self._summary_messages(question, evidence)
        return self._messages(question, evidence)

    # ------------------------------------------------------------------ 对外
    def answer(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
        allow_web: bool | None = None,
    ) -> Answer:
        started = time.perf_counter()
        summary = is_summary_query(question)
        if summary:
            evidence = self._summary_evidence(question, doc_ids)
            if evidence:
                try:
                    raw = self.llm.complete(
                        self._messages_for(question, evidence, True),
                        temperature=0.0,
                        max_tokens=self.settings.summary_max_tokens,
                        extra_body={"enable_thinking": False},
                    )
                except LLMError as exc:
                    raise LLMError(format_llm_error(str(exc))) from exc
                return self._finalize(question, raw, evidence, started)

        evidence, support = self._retrieve(question, doc_ids, top_k)
        if not evidence or support < self.settings.min_evidence_score:
            sources = self._search_web(question, allow_web)
            if sources:
                raw = self.llm.complete(
                    self._external_messages(question, sources), temperature=0.0
                )
                return self._finalize_external(question, raw, evidence, sources, started)
            return self._refusal(question, evidence, started)
        raw = self.llm.complete(self._messages(question, evidence))
        final = self._finalize(question, raw, evidence, started)
        if final.refused:
            sources = self._search_web(question, allow_web)
            if sources:
                raw = self.llm.complete(
                    self._external_messages(question, sources), temperature=0.0
                )
                return self._finalize_external(question, raw, evidence, sources, started)
        return final

    def _complete_answer(
        self,
        question: str,
        evidence: list[RetrievedChunk],
        sources: list[ExternalSource] | None,
        started: float,
        allow_web: bool | None,
        summary: bool = False,
    ) -> Answer:
        """一次性调用；流式失败时兜底。sources 非空表示走外部补充模式。"""
        try:
            if sources is not None:
                raw = self.llm.complete(
                    self._external_messages(question, sources), temperature=0.0
                )
                return self._finalize_external(question, raw, evidence, sources, started)
            raw = self.llm.complete(
                self._messages_for(question, evidence, summary),
                temperature=0.0 if summary else None,
                max_tokens=self.settings.summary_max_tokens if summary else None,
                extra_body={"enable_thinking": False} if summary else None,
            )
            final = self._finalize(question, raw, evidence, started)
            if final.refused and not summary:
                web = self._search_web(question, allow_web)
                if web:
                    raw = self.llm.complete(
                        self._external_messages(question, web), temperature=0.0
                    )
                    return self._finalize_external(question, raw, evidence, web, started)
            return final
        except LLMError as exc:
            raise LLMError(format_llm_error(str(exc))) from exc

    def stream_answer(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        top_k: int | None = None,
        allow_web: bool | None = None,
    ) -> Iterator[StreamEvent]:
        started = time.perf_counter()
        summary = is_summary_query(question)
        if summary:
            yield StreamEvent(kind="status", text="正在扫描本讲课件要点…")
            evidence = self._summary_evidence(question, doc_ids)
            if evidence:
                yield StreamEvent(kind="status", text="正在组织总结回答…")
                yield from self._stream_with(
                    question, evidence, started, allow_web=allow_web, summary=True
                )
                return

        yield StreamEvent(kind="status", text="正在检索相关课件页…")
        evidence, support = self._retrieve(question, doc_ids, top_k)
        if not evidence or support < self.settings.min_evidence_score:
            sources = self._search_web(question, allow_web)
            if not sources:
                final = self._refusal(question, evidence, started)
                yield StreamEvent(kind="final", text=final.answer, answer=final)
                return
            yield StreamEvent(kind="status", text="讲义证据不足，正在检索网络补充…")
            yield from self._stream_external(question, evidence, sources, started, allow_web)
            return

        yield StreamEvent(
            kind="status",
            text=f"已定位 {len(evidence)} 处证据，正在生成回答…",
        )
        yield from self._stream_with(question, evidence, started, allow_web=allow_web)

    def _stream_with(
        self,
        question: str,
        evidence: list[RetrievedChunk],
        started: float,
        *,
        allow_web: bool | None,
        summary: bool = False,
    ) -> Iterator[StreamEvent]:
        stream_failed: LLMError | None = None
        buffer: list[str] = []
        try:
            for delta in self.llm.stream(
                self._messages_for(question, evidence, summary),
                temperature=0.0 if summary else None,
                max_tokens=self.settings.summary_max_tokens if summary else None,
                extra_body={"enable_thinking": False} if summary else None,
            ):
                buffer.append(delta)
                yield StreamEvent(kind="delta", text=delta)
        except LLMError as exc:
            stream_failed = exc

        if stream_failed is None:
            final = self._finalize(question, "".join(buffer), evidence, started)
            if final.refused and not summary:
                sources = self._search_web(question, allow_web)
                if sources:
                    try:
                        external_buffer: list[str] = []
                        for delta in self.llm.stream(
                            self._external_messages(question, sources), temperature=0.0
                        ):
                            external_buffer.append(delta)
                            yield StreamEvent(kind="delta", text=delta)
                    except LLMError:
                        with contextlib.suppress(LLMError):
                            final = self._complete_answer(
                                question, evidence, sources, started, allow_web
                            )
                    else:
                        final = self._finalize_external(
                            question, "".join(external_buffer), evidence, sources, started
                        )
            yield StreamEvent(kind="final", text=final.answer, answer=final)
            return

        try:
            final = self._complete_answer(
                question, evidence, None, started, allow_web, summary=summary
            )
        except LLMError as fallback_exc:
            yield StreamEvent(
                kind="error",
                text=format_llm_error(str(fallback_exc) or str(stream_failed)),
            )
            return
        yield StreamEvent(kind="final", text=final.answer, answer=final)

    def _stream_external(
        self,
        question: str,
        evidence: list[RetrievedChunk],
        sources: list[ExternalSource],
        started: float,
        allow_web: bool | None,
    ) -> Iterator[StreamEvent]:
        buffer: list[str] = []
        try:
            for delta in self.llm.stream(
                self._external_messages(question, sources), temperature=0.0
            ):
                buffer.append(delta)
                yield StreamEvent(kind="delta", text=delta)
        except LLMError as exc:
            try:
                final = self._complete_answer(
                    question, evidence, sources, started, allow_web
                )
            except LLMError as fallback_exc:
                yield StreamEvent(
                    kind="error",
                    text=format_llm_error(str(fallback_exc) or str(exc)),
                )
                return
            yield StreamEvent(kind="final", text=final.answer, answer=final)
            return
        final = self._finalize_external(question, "".join(buffer), evidence, sources, started)
        yield StreamEvent(kind="final", text=final.answer, answer=final)
