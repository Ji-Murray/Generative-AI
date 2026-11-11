"""课程地图：逐讲覆盖整份讲义的「分段笔记 → 合并卡片」+ 课程层总览。

三级生成，全部落盘缓存：
1. 一讲超过 GROUP_SLIDES 页时，按页顺序切成若干段，每段生成「分段笔记」（summary/topics/
   concepts/objectives），保证每一页都进入模型上下文，不靠抽样；
2. 把该讲所有分段笔记合并成一讲学习卡片（summary/topics/objectives/concepts/key_pages），
   缓存到 var/learning/lectures/<doc_id>.json，按该讲语料指纹失效；
3. 汇总各讲卡片生成课程层总览与各讲关系（不改写各讲细节），缓存到 var/learning/outline.json。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from lectureqa.config import Settings
from lectureqa.llm import LLM, LLMError
from lectureqa.retrieval.corpus import Corpus
from lectureqa.schemas import Chunk, CourseOutline, DocumentInfo, LectureOutline
from lectureqa.textutils import extract_lecture_number, is_sample_lecture, lecture_sort_key

logger = logging.getLogger(__name__)

GROUP_SLIDES = 28
SLIDE_CHARS = 220
OUTLINE_SCHEMA_VERSION = "ranges-v1"
_RANGE_RE = re.compile(r"p\.(\d+)(?:\s*[-–—~～至到]\s*(\d+))?", re.IGNORECASE)

LECTURE_SYSTEM = (
    "你是课程助教，负责把一讲课件梳理成学习卡片。\n"
    "输入是该讲按页顺序给出的幻灯片内容。\n"
    "只依据输入内容作答，不要引入讲义之外的知识，也不要把页面噪声当成主题。\n"
    "只输出一个 JSON 对象，不要 Markdown 代码块或任何解释：\n"
    '{"title": str, "summary": str, "topics": [str], "objectives": [str], '
    '"concepts": [str], "key_pages": [int]}\n'
    "要求：\n"
    "1. summary 120-200 字：这一讲要解决什么问题、按什么脉络展开、核心方法或结论是什么。\n"
    "2. topics 必须写成页码区间「p.起始-结束 主题：一句话要点」（单页写成 p.N）；"
    "按页码顺序排列，区间首尾相接，覆盖输入中出现的全部页码，不要只抽若干散点页。\n"
    "3. objectives 给 3-5 条可检验的学习目标；concepts 给 4-8 个术语或方法名。\n"
    "4. key_pages 给各 topics 区间的起始页（3-8 个），只能取自输入中出现过的页码。"
)

PARTIAL_SYSTEM = (
    "你是课程助教，正在分段阅读一讲课件，之后会把各段笔记合并成整讲卡片。\n"
    "输入是这一讲中连续的一段幻灯片内容。\n"
    "只依据输入内容作答；只输出一个 JSON 对象：\n"
    '{"summary": str, "topics": [str], "concepts": [str], "objectives": [str]}\n'
    "要求：\n"
    "1. summary 用 60-100 字说清这一段讲了什么、推进到什么结论，不要写「本段」「以上」这类元叙述。\n"
    "2. topics 给 2-5 条「p.起始-结束 主题：一句话要点」，区间覆盖本段全部页码且首尾相接。\n"
    "3. concepts 给 0-6 个术语；objectives 给 0-3 条可检验目标（没有就给空数组）。"
)

MERGE_SYSTEM = (
    "你是课程设计助教。输入是同一讲按页顺序得到的分段笔记。\n"
    "请把它们合并成一讲的学习卡片，只输出一个 JSON 对象：\n"
    '{"title": str, "summary": str, "topics": [str], "objectives": [str], '
    '"concepts": [str], "key_pages": [int]}\n'
    "要求：\n"
    "1. summary 120-200 字，写成一段连贯的话，覆盖这一讲从开头到结尾的完整脉络。\n"
    "2. topics 给 4-10 条「p.起始-结束 主题：一句话要点」，按页码顺序、区间首尾相接，"
    "覆盖整讲从第一页到最后一页，不要只列散点页。\n"
    "3. objectives 给 3-5 条；concepts 给 4-8 个，去重合并同义项。\n"
    "4. key_pages 给各 topics 区间的起始页，只能来自分段笔记中出现过的页码。\n"
    "5. 不要编造分段笔记里没有的主题，也不要只是拼接各段摘要。"
)

COURSE_SYSTEM = (
    "你是课程设计助教。输入是已经生成好的各讲学习卡片（标题、摘要、关键概念）。\n"
    "只输出一个 JSON 对象：\n"
    '{"course_title": str, "overview": str, "relations": [str]}\n'
    "要求：\n"
    "1. overview 用 3-4 句说明这门课讲什么、按什么顺序展开、学完能做什么。\n"
    "2. relations 给 3-6 条，说明讲与讲之间的依赖或递进关系，用「第X讲 ↔ 第Y讲：……」表述。\n"
    "3. 不要改写或重复各讲摘要，也不要编造输入里没有的主题。"
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def fingerprint(documents: list[DocumentInfo], chunks: list[Chunk]) -> str:
    signature = "|".join(
        sorted(f"{document.doc_id}:{document.pages}:{document.chunks}" for document in documents)
    )
    signature += f"#{len(chunks)}#{OUTLINE_SCHEMA_VERSION}"
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]


def lecture_fingerprint(chunks: list[Chunk]) -> str:
    signature = "|".join(
        f"{chunk.chunk_id}:{len(chunk.text)}"
        for chunk in sorted(chunks, key=lambda item: (item.page, item.chunk_index))
    )
    signature = f"{OUTLINE_SCHEMA_VERSION}|{signature}"
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]


def parse_topic_span(topic: str) -> tuple[int, int] | None:
    """解析「p.3-7 …」或「p.3 …」为闭区间 [start, end]。"""
    match = _RANGE_RE.search(topic or "")
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    if end < start:
        start, end = end, start
    return start, end


def format_topic_span(start: int, end: int, body: str) -> str:
    body = " ".join((body or "").split()).strip(" ：:-—") or "要点"
    if start == end:
        return f"p.{start} {body}"
    return f"p.{start}-{end} {body}"


def _page_labels(slides: list[Chunk]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for chunk in sorted(slides, key=lambda item: (item.page, item.chunk_index)):
        text = " ".join(chunk.text.split())
        if len(text) < 8:
            continue
        labels.setdefault(chunk.page, text[:40])
    return labels


def _merge_span_count(
    spans: list[tuple[int, int, str]], limit: int
) -> list[tuple[int, int, str]]:
    """区间过多时合并最短相邻段，控制 topics 条数。"""
    items = list(spans)
    while len(items) > limit and len(items) >= 2:
        best = 0
        best_width = items[0][1] - items[0][0] + items[1][1] - items[1][0]
        for index in range(1, len(items) - 1):
            width = (
                items[index][1]
                - items[index][0]
                + items[index + 1][1]
                - items[index + 1][0]
            )
            if width < best_width:
                best = index
                best_width = width
        left = items[best]
        right = items[best + 1]
        items[best : best + 2] = [(left[0], right[1], f"{left[2]}；{right[2]}")]
    return items


def ensure_topic_coverage(
    topics: list[str],
    allowed: set[int],
    slides: list[Chunk],
    *,
    limit: int = 10,
) -> list[str]:
    """把 topics 规范成覆盖 allowed 全部页码的连续区间列表。"""
    if not allowed:
        return topics[:limit]

    page_min, page_max = min(allowed), max(allowed)
    labels = _page_labels(slides)
    spans: list[tuple[int, int, str]] = []
    for topic in topics:
        span = parse_topic_span(topic)
        if span is None:
            continue
        start = max(span[0], page_min)
        end = min(span[1], page_max)
        if start > end:
            continue
        body = _RANGE_RE.sub("", topic, count=1).strip(" ：:-—") or labels.get(
            start, "要点"
        )
        spans.append((start, end, body))

    if not spans:
        return _fallback_topics(slides, segments=min(limit, max(len(allowed), 1)))[:limit]

    spans.sort(key=lambda item: item[0])
    covered: set[int] = set()
    normalized: list[tuple[int, int, str]] = []
    for start, end, body in spans:
        normalized.append((start, end, body))
        covered.update(page for page in range(start, end + 1) if page in allowed)

    missing = sorted(page for page in allowed if page not in covered)
    if missing:
        gap_start = missing[0]
        prev = missing[0]
        for page in missing[1:]:
            if page == prev + 1:
                prev = page
                continue
            normalized.append(
                (gap_start, prev, labels.get(gap_start, f"第 {gap_start}-{prev} 页内容"))
            )
            gap_start = prev = page
        normalized.append(
            (gap_start, prev, labels.get(gap_start, f"第 {gap_start}-{prev} 页内容"))
        )

    normalized.sort(key=lambda item: item[0])
    normalized = _merge_span_count(normalized, limit)
    return [format_topic_span(start, end, body) for start, end, body in normalized]


def topic_key_pages(topics: list[str], allowed: set[int], *, limit: int = 8) -> list[int]:
    pages: list[int] = []
    for topic in topics:
        span = parse_topic_span(topic)
        if span is None:
            continue
        start = span[0]
        if start in allowed and start not in pages:
            pages.append(start)
        if len(pages) >= limit:
            break
    return pages


def group_slides(chunks: list[Chunk], limit: int = GROUP_SLIDES) -> list[list[Chunk]]:
    """按页顺序切段，保证每一页都进入某一组，不丢内容。"""
    ordered = sorted(chunks, key=lambda item: (item.page, item.chunk_index))
    if not ordered:
        return []
    return [ordered[index : index + limit] for index in range(0, len(ordered), limit)]


def _slide_block(slides: list[Chunk]) -> str:
    lines = []
    for chunk in slides:
        text = " ".join(chunk.text.split())[:SLIDE_CHARS]
        if not text:
            continue
        lines.append(f"[p.{chunk.page}] {text}")
    return "\n".join(lines)


def _base_prompt(document: DocumentInfo, slides: list[Chunk]) -> str:
    return (
        f"讲义 doc_id: {document.doc_id}\n"
        f"讲义文件名: {document.doc_title}\n"
        f"总页数: {document.pages}\n"
        f"本次给出 {len(slides)} 页幻灯片内容：\n"
        "<slides>\n"
        f"{_slide_block(slides)}\n"
        "</slides>\n"
    )


def _lecture_messages(document: DocumentInfo, slides: list[Chunk]) -> list[dict[str, str]]:
    user = (
        f"{_base_prompt(document, slides)}\n"
        "请输出这一讲的学习卡片 JSON，topics 要体现从开头到结尾的完整脉络。"
    )
    return [
        {"role": "system", "content": LECTURE_SYSTEM},
        {"role": "user", "content": user},
    ]


def _partial_messages(
    document: DocumentInfo, slides: list[Chunk], index: int, total: int
) -> list[dict[str, str]]:
    user = (
        f"{_base_prompt(document, slides)}\n"
        f"这是该讲的第 {index}/{total} 段。请输出这一段的分段笔记 JSON。"
    )
    return [
        {"role": "system", "content": PARTIAL_SYSTEM},
        {"role": "user", "content": user},
    ]


def _merge_messages(document: DocumentInfo, partials: list[dict]) -> list[dict[str, str]]:
    blocks = []
    for index, partial in enumerate(partials, start=1):
        topics = "\n".join(f"  - {item}" for item in partial.get("topics", []))
        blocks.append(
            f"第 {index} 段摘要：{partial.get('summary', '')}\n"
            f"第 {index} 段要点：\n{topics or '  - （无）'}\n"
            f"第 {index} 段概念：{'、'.join(partial.get('concepts', []))}"
        )
    user = (
        f"讲义 doc_id: {document.doc_id}\n"
        f"讲义文件名: {document.doc_title}\n"
        f"总页数: {document.pages}\n"
        "<partials>\n" + "\n\n".join(blocks) + "\n</partials>\n\n"
        "请把以上分段笔记合并成这一讲的学习卡片 JSON。"
    )
    return [
        {"role": "system", "content": MERGE_SYSTEM},
        {"role": "user", "content": user},
    ]


def _course_messages(lectures: list[LectureOutline]) -> list[dict[str, str]]:
    cards = []
    for lecture in lectures:
        cards.append(
            f"第{lecture.order}讲 · {lecture.title} (doc_id={lecture.doc_id})\n"
            f"摘要：{lecture.summary}\n"
            f"概念：{'、'.join(lecture.concepts)}\n"
            f"目标：{'；'.join(lecture.objectives)}"
        )
    return [
        {"role": "system", "content": COURSE_SYSTEM},
        {"role": "user", "content": "<lectures>\n" + "\n\n".join(cards) + "\n</lectures>"},
    ]


def _clean_list(raw: object, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()][:limit]


def _dedupe(items: list[str], limit: int) -> list[str]:
    seen: list[str] = []
    for item in items:
        text = item.strip()
        if text and text not in seen:
            seen.append(text)
    return seen[:limit]


def _clean_pages(raw: object, allowed: set[int]) -> list[int]:
    if not isinstance(raw, list):
        return []
    pages: list[int] = []
    for item in raw:
        try:
            page = int(item)
        except (TypeError, ValueError):
            continue
        if page in allowed and page not in pages:
            pages.append(page)
    return pages


def _fallback_topics(slides: list[Chunk], segments: int = 6) -> list[str]:
    """无模型结果时，按页顺序切成若干连续区间，保证全页覆盖。"""
    pages = sorted({chunk.page for chunk in slides})
    if not pages:
        return []
    labels = _page_labels(slides)
    count = min(max(segments, 1), len(pages))
    topics: list[str] = []
    for index in range(count):
        start_idx = index * len(pages) // count
        end_idx = (index + 1) * len(pages) // count - 1
        start, end = pages[start_idx], pages[end_idx]
        topics.append(format_topic_span(start, end, labels.get(start, f"第 {start} 页起")))
    return topics


def _fallback_lecture(document: DocumentInfo, slides: list[Chunk]) -> LectureOutline:
    joined = " ".join(" ".join(chunk.text.split()) for chunk in slides)
    topics = _fallback_topics(slides)
    allowed = {chunk.page for chunk in slides}
    return LectureOutline(
        doc_id=document.doc_id,
        order=1,
        title=" ".join(document.doc_title.replace("_", " ").split()),
        summary=joined[:200],
        topics=topics,
        key_pages=topic_key_pages(topics, allowed) or [chunk.page for chunk in slides[:4]],
    )


def _from_partials(
    document: DocumentInfo, partials: list[dict], slides: list[Chunk]
) -> LectureOutline:
    summary = " ".join(str(p.get("summary", "")).strip() for p in partials).strip()
    topics: list[str] = []
    concepts: list[str] = []
    objectives: list[str] = []
    for partial in partials:
        topics.extend(str(item) for item in partial.get("topics", []) or [])
        concepts.extend(str(item) for item in partial.get("concepts", []) or [])
        objectives.extend(str(item) for item in partial.get("objectives", []) or [])
    allowed = {chunk.page for chunk in slides}
    topics = ensure_topic_coverage(topics, allowed, slides)
    return LectureOutline(
        doc_id=document.doc_id,
        order=1,
        title=" ".join(document.doc_title.replace("_", " ").split()),
        summary=summary[:600] or _fallback_lecture(document, slides).summary,
        topics=topics,
        objectives=_dedupe(objectives, 5),
        concepts=_dedupe(concepts, 8),
        key_pages=topic_key_pages(topics, allowed) or [chunk.page for chunk in slides[:4]],
    )


def _coerce_lecture(
    raw: dict, document: DocumentInfo, allowed_pages: set[int], slides: list[Chunk]
) -> LectureOutline:
    title = str(raw.get("title", "")).strip() or document.doc_title
    title = " ".join(title.replace("_", " ").split())
    summary = str(raw.get("summary", "")).strip()
    if not summary:
        summary = _fallback_lecture(document, slides).summary
    topics = ensure_topic_coverage(_clean_list(raw.get("topics"), 12), allowed_pages, slides)
    key_pages = _clean_pages(raw.get("key_pages"), allowed_pages)
    if not key_pages:
        key_pages = topic_key_pages(topics, allowed_pages) or [chunk.page for chunk in slides[:4]]
    return LectureOutline(
        doc_id=document.doc_id,
        order=1,
        title=title,
        summary=summary,
        topics=topics,
        objectives=_clean_list(raw.get("objectives"), 5),
        concepts=_clean_list(raw.get("concepts"), 8),
        key_pages=key_pages,
    )


def order_lectures(lectures: list[LectureOutline]) -> list[LectureOutline]:
    """按讲次编号重排，并使 order = 文件名/标题中的讲次（Lecture3 → 第3讲）。

    示例课件（lecture02-transformer）排在正式讲义之后，order 从 101 起，避免挤占第 N 讲。
    """
    ordered = sorted(
        lectures,
        key=lambda item: lecture_sort_key(item.doc_id, item.title),
    )
    result: list[LectureOutline] = []
    sample_index = 0
    for item in ordered:
        number = extract_lecture_number(item.doc_id, item.title)
        if is_sample_lecture(item.doc_id):
            sample_index += 1
            order = 100 + sample_index
        else:
            order = number or (len(result) + 1)
        result.append(item.model_copy(update={"order": order}))
    return result


def order_documents(documents: list[DocumentInfo]) -> list[DocumentInfo]:
    return sorted(
        documents,
        key=lambda item: lecture_sort_key(item.doc_id, item.doc_title, item.source_path),
    )


def lectures_dir(settings: Settings) -> Path:
    return settings.learning_dir / "lectures"


def _lecture_cache_path(settings: Settings, doc_id: str) -> Path:
    return lectures_dir(settings) / f"{doc_id}.json"


def _load_cached_lecture(settings: Settings, doc_id: str, fp: str) -> LectureOutline | None:
    path = _lecture_cache_path(settings, doc_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if payload.get("fingerprint") != fp:
        return None
    try:
        return LectureOutline.model_validate(payload.get("outline"))
    except ValueError:
        return None


def _save_cached_lecture(settings: Settings, lecture: LectureOutline, fp: str) -> None:
    path = _lecture_cache_path(settings, lecture.doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"fingerprint": fp, "outline": lecture.model_dump()}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )


def _llm_json(llm: LLM, messages: list[dict[str, str]], max_tokens: int) -> dict:
    return llm.complete_json(
        messages,
        temperature=0.2,
        max_tokens=max_tokens,
        extra_body={"enable_thinking": False},
    )


def _build_one_lecture(
    settings: Settings,
    llm: LLM,
    document: DocumentInfo,
    chunks: list[Chunk],
    *,
    refresh: bool,
) -> LectureOutline:
    fp = lecture_fingerprint(chunks)
    if not refresh:
        cached = _load_cached_lecture(settings, document.doc_id, fp)
        if cached is not None:
            return cached

    groups = group_slides(chunks)
    allowed = {chunk.page for chunk in chunks}
    budget = min(settings.summary_max_tokens, 1600)

    try:
        if len(groups) <= 1:
            raw = _llm_json(llm, _lecture_messages(document, groups[0]), budget)
            lecture = _coerce_lecture(raw, document, allowed, groups[0])
        else:
            partials: list[dict] = []
            for index, group in enumerate(groups, start=1):
                raw = _llm_json(
                    llm,
                    _partial_messages(document, group, index, len(groups)),
                    max_tokens=600,
                )
                partials.append(raw)
            merged = _llm_json(llm, _merge_messages(document, partials), budget)
            lecture = _coerce_lecture(merged, document, allowed, chunks)
    except (LLMError, ValueError) as exc:
        logger.warning("第 %s 讲卡片生成失败（%s），退回抽取式", document.doc_id, exc)
        lecture = _fallback_lecture(document, chunks)

    _save_cached_lecture(settings, lecture, fp)
    return lecture


def _build_course(
    settings: Settings, llm: LLM, lectures: list[LectureOutline]
) -> tuple[str, str, list[str]]:
    try:
        raw = _llm_json(
            llm, _course_messages(lectures), max_tokens=min(settings.summary_max_tokens, 1200)
        )
    except (LLMError, ValueError) as exc:
        logger.warning("课程层大纲生成失败（%s），退回抽取式", exc)
        titles = "、".join(f"第{item.order}讲 {item.title}" for item in lectures)
        return "课程大纲", f"本课程共 {len(lectures)} 讲：{titles}。", []

    course_title = str(raw.get("course_title", "")).strip() or "课程大纲"
    overview = str(raw.get("overview", "")).strip()
    if not overview:
        titles = "、".join(f"第{item.order}讲 {item.title}" for item in lectures)
        overview = f"本课程共 {len(lectures)} 讲：{titles}。"
    return course_title, overview, _clean_list(raw.get("relations"), 6)


def outline_path(settings: Settings) -> Path:
    return settings.learning_dir / "outline.json"


def load_outline(settings: Settings, fingerprint_value: str) -> CourseOutline | None:
    path = outline_path(settings)
    if not path.exists():
        return None
    try:
        outline = CourseOutline.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        logger.warning("outline.json 读取失败，将重新生成")
        return None
    if outline.fingerprint != fingerprint_value:
        return None
    return outline


def save_outline(settings: Settings, outline: CourseOutline) -> None:
    path = outline_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(outline.model_dump(), ensure_ascii=False, indent=2)
    path.write_text(payload, encoding="utf-8")


def build_outline(
    settings: Settings,
    llm: LLM,
    corpus: Corpus,
    documents: list[DocumentInfo],
    *,
    refresh: bool = False,
    max_workers: int = 4,
) -> CourseOutline:
    chunks = corpus.chunks
    fingerprint_value = fingerprint(documents, chunks)
    if not documents:
        return CourseOutline(
            course_title="课程大纲",
            overview="尚未导入讲义：请先上传 PDF 并构建索引。",
            generated_at=_now(),
            fingerprint=fingerprint_value,
        )

    documents = order_documents(documents)

    if not refresh:
        cached = load_outline(settings, fingerprint_value)
        if cached is not None:
            cached.lectures = order_lectures(cached.lectures)
            cached.learning_path = [item.doc_id for item in cached.lectures]
            return cached

    by_doc: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.doc_id, []).append(chunk)

    lectures_by_id: dict[str, LectureOutline] = {}
    pending = [document for document in documents if by_doc.get(document.doc_id)]
    if pending:
        workers = max(1, min(max_workers, len(pending)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _build_one_lecture,
                    settings,
                    llm,
                    document,
                    by_doc[document.doc_id],
                    refresh=refresh,
                ): document
                for document in pending
            }
            for future in as_completed(futures):
                document = futures[future]
                try:
                    lectures_by_id[document.doc_id] = future.result()
                except Exception as exc:  # noqa: BLE001 - 单讲失败不能拖垮整门课
                    logger.warning("第 %s 讲处理失败：%s", document.doc_id, exc)
                    lectures_by_id[document.doc_id] = _fallback_lecture(
                        document, by_doc[document.doc_id]
                    )

    lectures: list[LectureOutline] = []
    for document in documents:
        lecture = lectures_by_id.get(document.doc_id)
        if lecture is None:
            lecture = LectureOutline(
                doc_id=document.doc_id,
                order=1,
                title=document.doc_title,
                summary="",
            )
        lectures.append(lecture)

    lectures = order_lectures(lectures)
    course_title, overview, relations = _build_course(settings, llm, lectures)
    outline = CourseOutline(
        course_title=course_title,
        overview=overview,
        learning_path=[item.doc_id for item in lectures],
        lectures=lectures,
        relations=relations,
        generated_at=_now(),
        fingerprint=fingerprint_value,
    )
    save_outline(settings, outline)
    return outline
