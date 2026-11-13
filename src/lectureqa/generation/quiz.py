"""Quiz 生成：结构化输出 + 逐题校验 + 不可溯源题目直接丢弃。"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from lectureqa.config import Settings
from lectureqa.generation import prompts
from lectureqa.llm import LLM, LLMError
from lectureqa.retrieval.retriever import Retriever
from lectureqa.schemas import (
    DIFFICULTIES,
    QuestionType,
    QuizQuestion,
    QuizResult,
    QuizSource,
    RetrievedChunk,
)

_TYPE_ALIASES = {
    "mcq": QuestionType.mcq,
    "multiple_choice": QuestionType.mcq,
    "multiple-choice": QuestionType.mcq,
    "single_choice": QuestionType.mcq,
    "choice": QuestionType.mcq,
    "true_false": QuestionType.true_false,
    "truefalse": QuestionType.true_false,
    "true/false": QuestionType.true_false,
    "boolean": QuestionType.true_false,
    "tf": QuestionType.true_false,
    "short_answer": QuestionType.short_answer,
    "short": QuestionType.short_answer,
    "open": QuestionType.short_answer,
    "qa": QuestionType.short_answer,
}

_OPTION_PREFIX = re.compile(r"^\s*[A-Da-d][.、):：]\s*")
_TRUE_WORDS = {"true", "t", "对", "正确", "是的", "√"}
_FALSE_WORDS = {"false", "f", "错", "错误", "不对", "×"}
# 标题/讲次/页码/幻灯片等元信息题：考的是课件壳子，不是知识点
_META_QUESTION_RE = re.compile(
    r"("
    r"标题|题目名称|课件名|讲义名|文件名|课程名|course\s*title|lecture\s*title|"
    r"本讲(的)?(名称|标题|名字)|这一讲叫|第\s*\d+\s*讲(叫|的标题|的名称)|"
    r"lecture\s*\d+\s*(叫|is|title)|what\s+is\s+the\s+title|"
    r"封面|目录页|agenda|outline\s*title|作者是谁|讲师是谁|"
    # 问「第N页讲了什么 / PPT哪页 / 答案是页码」
    r"第\s*\d+\s*页.{0,16}(讲了什么|说了什么|内容(是|有)|题目是|标题是|写了什么|提到什么)|"
    r"(ppt|PPT|课件|幻灯片|slide|讲义).{0,12}(第\s*\d+\s*页|p\.?\s*\d+)|"
    r"(哪一页|第几页|在哪一?页|页码是多少|what\s+page|which\s+page|on\s+which\s+(page|slide))|"
    r"(page|slide)\s*\d+.{0,24}(about|discuss|title|content|say|讲了|说了|内容)|"
    r"(内容在|出现在|写在).{0,10}(第\s*\d+\s*页|page\s*\d+|p\.?\s*\d+)"
    r")",
    re.IGNORECASE,
)

_PAGE_ANSWER_QUESTION_RE = re.compile(
    r"(哪一页|第几页|在哪一?页|页码|which\s+page|what\s+page|on\s+which\s+slide)",
    re.IGNORECASE,
)
_PAGE_ANSWER_RE = re.compile(
    r"^\s*(第\s*\d+\s*页|p\.?\s*\d+|page\s*\d+|slide\s*\d+)\s*$",
    re.IGNORECASE,
)


def is_meta_question(text: str) -> bool:
    """是否在考讲义标题/页码/幻灯片位置等壳信息，而不是正文考点。"""
    return bool(_META_QUESTION_RE.search(text or ""))


def is_page_locator_question(question: str, answer: str = "") -> bool:
    """题干在问页码位置，或答案本身只是页码。"""
    q = question or ""
    a = str(answer or "").strip()
    if _PAGE_ANSWER_QUESTION_RE.search(q):
        return True
    return bool(a and _PAGE_ANSWER_RE.match(a))


class QuizGenerationError(RuntimeError):
    pass


def _normalize_type(raw: Any) -> QuestionType | None:
    if isinstance(raw, QuestionType):
        return raw
    if not isinstance(raw, str):
        return None
    return _TYPE_ALIASES.get(raw.strip().lower())


def _clean_options(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [_OPTION_PREFIX.sub("", str(option)).strip() for option in raw if str(option).strip()]


def _normalize_mcq_answer(raw: Any, options: list[str]) -> str | None:
    if isinstance(raw, bool):
        return None
    text = str(raw).strip()
    letter = text.upper()
    if letter in {"A", "B", "C", "D"}:
        return letter if ord(letter) - ord("A") < len(options) else None
    for index, option in enumerate(options):
        if option and option.lower() == text.lower():
            return chr(ord("A") + index)
    match = re.match(r"^([A-D])[.、):：\s]", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def _normalize_bool_answer(raw: Any) -> str | None:
    text = str(raw).strip().lower()
    if text in _TRUE_WORDS:
        return "True"
    if text in _FALSE_WORDS:
        return "False"
    return None


def _parse_sources(raw: Any) -> list[QuizSource]:
    sources: list[QuizSource] = []
    if not isinstance(raw, list):
        return sources
    for item in raw:
        if isinstance(item, dict):
            doc_id = item.get("doc_id") or item.get("doc") or item.get("lecture")
            page = item.get("page") or item.get("p") or item.get("page_number")
        elif isinstance(item, str):
            match = re.match(r"^(?P<doc>[^:]+):p?(?P<page>\d+)$", item.strip())
            if not match:
                continue
            doc_id, page = match.group("doc"), match.group("page")
        else:
            continue
        try:
            page_number = int(page)
        except (TypeError, ValueError):
            continue
        if not doc_id:
            continue
        sources.append(QuizSource(doc_id=str(doc_id).strip(), page=page_number))
    return sources


def validate_question(
    raw: dict[str, Any],
    keys: set[tuple[str, int]],
    index: int,
) -> tuple[QuizQuestion | None, dict[str, Any] | None]:
    """返回 (合法题目 | None, 丢弃原因 | None)。"""
    question_type = _normalize_type(raw.get("type"))
    if question_type is None:
        return None, {"index": index, "reason": "未知题型", "raw": raw}

    text = str(raw.get("question") or "").strip()
    if not text:
        return None, {"index": index, "reason": "题干为空", "raw": raw}
    if is_meta_question(text):
        return None, {
            "index": index,
            "reason": "元信息题（标题/页码/幻灯片等），非内容考点",
            "raw": raw,
        }
    if is_page_locator_question(text, str(raw.get("answer") or "")):
        return None, {
            "index": index,
            "reason": "页码定位题（问第几页/答案是页码），非内容考点",
            "raw": raw,
        }

    explanation = str(raw.get("explanation") or raw.get("rationale") or "").strip()
    if not explanation:
        return None, {"index": index, "reason": "缺少解析", "raw": raw}

    sources = _parse_sources(raw.get("sources"))
    if not sources:
        return None, {"index": index, "reason": "缺少出处", "raw": raw}
    if not any((source.doc_id, source.page) in keys for source in sources):
        return None, {"index": index, "reason": "出处不在检索证据中", "raw": raw}

    options = _clean_options(raw.get("options"))
    answer_raw = raw.get("answer")

    if question_type is QuestionType.mcq:
        if len(options) < 3:
            return None, {"index": index, "reason": "选择题选项不足 3 项", "raw": raw}
        answer = _normalize_mcq_answer(answer_raw, options)
        if answer is None:
            return None, {"index": index, "reason": "选择题正确答案无法解析", "raw": raw}
    elif question_type is QuestionType.true_false:
        answer = _normalize_bool_answer(answer_raw)
        if answer is None:
            return None, {"index": index, "reason": "判断题答案无法解析", "raw": raw}
        options = ["True", "False"]
    else:
        answer = str(answer_raw or "").strip()
        if not answer:
            return None, {"index": index, "reason": "简答题缺少参考答案", "raw": raw}
        options = []

    difficulty = str(raw.get("difficulty") or "medium").strip().lower()
    if difficulty not in DIFFICULTIES:
        difficulty = "medium"

    if is_page_locator_question(text, answer):
        return None, {
            "index": index,
            "reason": "页码定位题（问第几页/答案是页码），非内容考点",
            "raw": raw,
        }
    if question_type is QuestionType.mcq and options:
        page_like = sum(1 for option in options if _PAGE_ANSWER_RE.match(option))
        if page_like >= max(2, len(options) // 2):
            return None, {
                "index": index,
                "reason": "选项多为页码，非内容考点",
                "raw": raw,
            }

    return (
        QuizQuestion(
            question_id=f"q{index + 1}",
            type=question_type,
            difficulty=difficulty,  # type: ignore[arg-type]
            question=text,
            options=options,
            answer=answer,
            explanation=explanation,
            sources=sources,
            grounded=True,
        ),
        None,
    )


class QuizGenerator:
    def __init__(self, retriever: Retriever, llm: LLM, settings: Settings) -> None:
        self.retriever = retriever
        self.llm = llm
        self.settings = settings

    def _evidence(
        self, topic: str, doc_ids: list[str] | None, n: int
    ) -> list[RetrievedChunk]:
        # 主题若像讲次标题，改写成考点检索，避免只召回封面/标题页
        query = (topic or "").strip()
        if is_meta_question(query) or re.search(
            r"(?i)^\s*(lecture|第)\s*\d+|标题|overview|本讲核心",
            query,
        ):
            query = f"{query} 定义 公式 算法 性质 步骤 优缺点 损失函数"
        return self.retriever.retrieve(
            query, doc_ids=doc_ids, top_k=min(max(n + 4, self.settings.top_k), 14)
        )

    def generate(
        self,
        topic: str,
        *,
        doc_ids: list[str] | None = None,
        n: int = 5,
        difficulty: str = "mixed",
        types: list[str] | None = None,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> QuizResult:
        def _progress(value: float, label: str) -> None:
            if on_progress is not None:
                on_progress(max(0.0, min(1.0, value)), label)

        n = max(1, min(n, self.settings.quiz_max_questions))
        type_list = types or ["mcq", "true_false", "short_answer"]
        _progress(0.12, "正在检索讲义正文考点…")
        evidence = self._evidence(topic, doc_ids, n)
        support = self.retriever.best_support(evidence)
        if not evidence or support < self.settings.min_evidence_score:
            _progress(1.0, "未找到足够考点证据")
            return QuizResult(
                topic=topic,
                questions=[],
                dropped=[{"reason": "讲义中没有找到与主题相关的证据", "support": support}],
                evidence=evidence,
                model=self.llm.model,
            )

        messages = [
            {"role": "system", "content": prompts.quiz_system_prompt(self.settings.default_language)},
            {
                "role": "user",
                "content": prompts.QUIZ_USER.format(
                    evidence=prompts.format_evidence(evidence),
                    topic=topic,
                    n=n,
                    types=", ".join(type_list),
                    difficulty=difficulty,
                ),
            },
        ]
        _progress(0.35, f"已定位 {len(evidence)} 处证据，正在调用模型出题…")
        payload = self.llm.complete_json(
            messages,
            max_tokens=max(self.settings.llm_max_tokens, 2200),
            extra_body={"enable_thinking": False},
        )
        raw_questions = payload.get("questions")
        if not isinstance(raw_questions, list):
            raise LLMError("Quiz 生成结果缺少 questions 数组")

        _progress(0.78, "正在校验题目出处与题干质量…")
        keys = {(item.chunk.doc_id, item.chunk.page) for item in evidence}
        questions: list[QuizQuestion] = []
        dropped: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_questions):
            if not isinstance(raw, dict):
                dropped.append({"index": index, "reason": "题目不是对象", "raw": raw})
                continue
            question, reason = validate_question(raw, keys, len(questions))
            if question is None:
                dropped.append(reason or {"index": index, "reason": "未知原因"})
                continue
            questions.append(question)
            frac = (index + 1) / max(len(raw_questions), 1)
            _progress(0.78 + 0.18 * frac, f"校验中（{index + 1}/{len(raw_questions)}）…")

        kept = questions[:n]
        _progress(1.0, f"出题完成：保留 {len(kept)} 题")
        return QuizResult(
            topic=topic,
            questions=kept,
            dropped=dropped + [{"reason": "超出请求题数"} for _ in questions[n:]],
            evidence=evidence,
            model=self.llm.model,
        )
