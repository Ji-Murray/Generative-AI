from __future__ import annotations

import json
import re

from lectureqa.learning.outline import (
    build_outline,
    ensure_topic_coverage,
    fingerprint,
    group_slides,
    lecture_fingerprint,
    parse_topic_span,
)
from lectureqa.learning.progress import ProgressStore
from lectureqa.llm import FakeLLM
from lectureqa.retrieval.corpus import Corpus
from lectureqa.schemas import Chunk, DocumentInfo


def _documents() -> list[DocumentInfo]:
    return [
        DocumentInfo(
            doc_id="lecture02_transformer",
            doc_title="Transformer 架构",
            source_path="a.pdf",
            pages=3,
            chunks=2,
        ),
        DocumentInfo(
            doc_id="lecture03_rag",
            doc_title="RAG 概述",
            source_path="b.pdf",
            pages=4,
            chunks=2,
        ),
    ]


def _pages_in(messages) -> list[str]:
    """取出提示词里的 [p.N] 页码，用于断言覆盖了哪些页。"""
    user = messages[-1]["content"]
    return [token.split("]")[0] for token in user.split("[p.")[1:]]


def _handler(messages) -> str:
    system = messages[0]["content"]
    user = messages[-1]["content"]

    if "分段阅读" in system:
        pages = _pages_in(messages)
        return json.dumps(
            {
                "summary": f"这一段覆盖页 {pages[0]}-{pages[-1]}。",
                "topics": [f"p.{pages[0]}-{pages[-1]} 主题：本段要点"],
                "concepts": ["概念一", "概念二"],
                "objectives": ["分段目标"],
            },
            ensure_ascii=False,
        )

    if "合并" in system:
        pages: list[int] = []
        for start, end in re.findall(r"p\.(\d+)(?:\s*[-–—~～至到]\s*(\d+))?", user):
            pages.append(int(start))
            pages.append(int(end or start))
        first, last = min(pages), max(pages)
        return json.dumps(
            {
                "title": "整讲标题",
                "summary": f"整讲摘要，覆盖页 {first}-{last}。",
                "topics": [f"p.{first}-{last} 主题：整讲要点"],
                "objectives": ["目标一", "目标二"],
                "concepts": ["概念一", "概念二", "概念三"],
                "key_pages": [first, last, 999],
            },
            ensure_ascii=False,
        )

    if "课程设计助教" in system:
        return json.dumps(
            {
                "course_title": "生成式 AI 专题",
                "overview": "这门课从 Transformer 讲到 RAG。",
                "relations": ["第1讲 ↔ 第2讲：注意力是检索增强生成的基础"],
            },
            ensure_ascii=False,
        )

    doc_id = next(
        line.split(":", 1)[1].strip()
        for line in user.splitlines()
        if line.startswith("讲义 doc_id:")
    )
    pages = _pages_in(messages)
    return json.dumps(
        {
            "title": doc_id.replace("_", " "),
            "summary": f"{doc_id} 的整讲摘要：从页 {pages[0]} 讲到页 {pages[-1]}。",
            "topics": [f"p.{pages[0]}-{pages[-1]} 主题：整讲脉络"],
            "objectives": ["目标一", "目标二"],
            "concepts": ["概念一", "概念二", "概念三"],
            "key_pages": [int(pages[0]), 999],
        },
        ensure_ascii=False,
    )


def _doc_chunks(corpus, doc_id):
    return [chunk for chunk in corpus.chunks if chunk.doc_id == doc_id]


def test_lecture_card_covers_whole_lecture(settings, corpus) -> None:
    llm = FakeLLM("", handler=_handler)
    outline = build_outline(settings, llm, corpus, _documents(), max_workers=1)

    assert [item.doc_id for item in outline.lectures] == [
        "lecture02_transformer",
        "lecture03_rag",
    ]
    assert outline.course_title == "生成式 AI 专题"
    assert outline.relations

    first = outline.lectures[0]
    assert first.doc_id == "lecture02_transformer"
    # 示例课件 order >= 100，不与正式「第 N 讲」抢编号
    assert first.order >= 100
    assert first.title == "lecture02 transformer"
    # key_pages 必须落在真实页面上：999 被丢弃
    assert first.key_pages == [2]
    assert first.topics and first.objectives and first.concepts

    # 整讲两页都进入同一讲上下文，而不只是第一块
    lecture_prompts = [
        call for call in llm.calls if "负责把一讲课件梳理成学习卡片" in call[0]["content"]
    ]
    assert len(lecture_prompts) == 2
    assert _pages_in(lecture_prompts[0]) == ["2", "3"]


def test_long_lecture_is_summarized_segment_by_segment(settings) -> None:
    chunks = [
        Chunk(
            chunk_id=f"big:p{page}:c0",
            doc_id="big",
            doc_title="超长讲义",
            page=page,
            chunk_index=0,
            text=f"第 {page} 页幻灯片内容，用于验证分段总结。",
        )
        for page in range(1, 71)
    ]
    corpus = Corpus(chunks)
    documents = [
        DocumentInfo(
            doc_id="big", doc_title="超长讲义", source_path="big.pdf", pages=70, chunks=70
        )
    ]
    llm = FakeLLM("", handler=_handler)
    outline = build_outline(settings, llm, corpus, documents, max_workers=1)

    partial_prompts = [call for call in llm.calls if "分段阅读" in call[0]["content"]]
    assert len(partial_prompts) == 3  # 70 页 / 每段 28 页

    seen_pages: set[str] = set()
    for call in partial_prompts:
        seen_pages.update(_pages_in(call))
    assert seen_pages == {str(page) for page in range(1, 71)}  # 每一页都被读过

    lecture = outline.lectures[0]
    assert lecture.key_pages == [1, 70]
    assert any(parse_topic_span(topic) and parse_topic_span(topic)[0] == 1 for topic in lecture.topics)
    assert any(parse_topic_span(topic) and parse_topic_span(topic)[1] == 70 for topic in lecture.topics)
    covered: set[int] = set()
    for topic in lecture.topics:
        span = parse_topic_span(topic)
        assert span is not None
        covered.update(range(span[0], span[1] + 1))
    assert covered == set(range(1, 71))


def test_parse_topic_span_and_full_coverage() -> None:
    assert parse_topic_span("p.3-7 注意力：公式推导") == (3, 7)
    assert parse_topic_span("p.12 总结") == (12, 12)
    assert parse_topic_span("p.2至5 开头") == (2, 5)

    slides = [
        Chunk(
            chunk_id=f"d:p{page}:c0",
            doc_id="d",
            doc_title="d",
            page=page,
            chunk_index=0,
            text=f"第{page}页内容足够长用于标签",
        )
        for page in range(1, 9)
    ]
    topics = ensure_topic_coverage(
        ["p.1-2 开场", "p.6-8 结尾"],
        allowed=set(range(1, 9)),
        slides=slides,
    )
    covered: set[int] = set()
    for topic in topics:
        span = parse_topic_span(topic)
        assert span is not None
        covered.update(range(span[0], span[1] + 1))
    assert covered == set(range(1, 9))
    assert any("3" in topic and "5" in topic for topic in topics)


def test_outline_is_cached(settings, corpus) -> None:
    documents = _documents()
    llm = FakeLLM("", handler=_handler)
    first = build_outline(settings, llm, corpus, documents, max_workers=1)
    calls_after_first = len(llm.calls)

    second = build_outline(settings, llm, corpus, documents, max_workers=1)

    assert len(llm.calls) == calls_after_first
    assert second.fingerprint == first.fingerprint
    assert (settings.learning_dir / "outline.json").exists()
    assert (settings.learning_dir / "lectures" / "lecture02_transformer.json").exists()


def test_lecture_cache_invalidated_by_chunk_change(settings, corpus, chunks) -> None:
    doc_id = "lecture02_transformer"
    before = lecture_fingerprint(_doc_chunks(corpus, doc_id))
    changed = [
        *_doc_chunks(corpus, doc_id),
        chunks[0].model_copy(
            update={"chunk_id": f"{doc_id}:p9:c0", "doc_id": doc_id, "page": 9, "text": "新增一页"}
        ),
    ]
    assert before != lecture_fingerprint(changed)


def test_outline_fingerprint_changes_with_corpus(settings, corpus, chunks) -> None:
    documents = _documents()
    before = fingerprint(documents, corpus.chunks)
    after = fingerprint(documents, [*corpus.chunks, chunks[0]])
    assert before != after


def test_outline_falls_back_when_llm_returns_garbage(settings, corpus) -> None:
    llm = FakeLLM("这不是 JSON")
    outline = build_outline(settings, llm, corpus, _documents(), max_workers=1)

    assert [item.doc_id for item in outline.lectures] == [
        "lecture02_transformer",
        "lecture03_rag",
    ]
    assert outline.lectures[0].summary
    assert "共 2 讲" in outline.overview
    assert outline.lectures[0].key_pages == [2, 3]


def test_group_slides_keeps_every_page_in_order() -> None:
    many = [
        Chunk(
            chunk_id=f"doc:p{page}:c0",
            doc_id="doc",
            doc_title="doc",
            page=page,
            chunk_index=0,
            text=f"第 {page} 页内容：这是一个足够长的幻灯片要点用于分段。",
        )
        for page in range(1, 61)
    ]
    groups = group_slides(many)
    assert [len(group) for group in groups] == [28, 28, 4]
    flat = [chunk.page for group in groups for chunk in group]
    assert flat == list(range(1, 61))
    assert group_slides([]) == []


def test_progress_store_persists_status_and_quiz(settings) -> None:
    store = ProgressStore(settings)
    store.set_status("lecture02_transformer", "learning")
    store.set_status("lecture02_transformer", "completed")
    store.record_quiz("lecture02_transformer", correct=3, total=5)

    reloaded = ProgressStore(settings).load()
    record = reloaded.lectures["lecture02_transformer"]
    assert record.status == "completed"
    assert record.quiz_attempts == 5
    assert record.quiz_correct == 3
    assert reloaded.updated_at
