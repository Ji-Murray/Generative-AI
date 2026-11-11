"""学习进度：按讲义记录学习状态、自测作答与薄弱点，持久化到 var/learning/progress.json。"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Literal

from lectureqa.config import Settings
from lectureqa.schemas import LearningState, LectureProgress, QuizAttempt, WeakPoint

Status = Literal["not_started", "learning", "completed"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def grade_quiz_answer(
    *,
    question_type: str,
    correct_answer: str,
    student_answer: str,
    options: list[str] | None = None,  # noqa: ARG001 - 预留与选项文本比对
) -> bool:
    """客观题严格比对；简答题看关键词重叠。"""
    gold = (correct_answer or "").strip()
    student = (student_answer or "").strip()
    if not student:
        return False
    qtype = (question_type or "").lower()
    if qtype in {"mcq", "multiple_choice"}:
        return student.upper()[:1] == gold.upper()[:1]
    if qtype in {"true_false", "truefalse", "boolean"}:
        def _bool_norm(text: str) -> str | None:
            value = text.strip().lower()
            if value in {"true", "t", "对", "正确", "是", "yes"}:
                return "true"
            if value in {"false", "f", "错", "错误", "否", "no"}:
                return "false"
            return None

        left, right = _bool_norm(student), _bool_norm(gold)
        return left is not None and left == right
    # short answer：字符级粗匹配
    gold_norm = "".join(gold.lower().split())
    student_norm = "".join(student.lower().split())
    if gold_norm and gold_norm in student_norm:
        return True
    gold_tokens = {
        token
        for token in gold.lower().replace("，", " ").replace(",", " ").split()
        if len(token) > 1
    }
    student_tokens = set(student.lower().replace("，", " ").replace(",", " ").split())
    if not gold_tokens:
        return student_norm == gold_norm
    overlap = len(gold_tokens & student_tokens) / len(gold_tokens)
    return overlap >= 0.5


class ProgressStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = settings.learning_dir / "progress.json"

    def load(self) -> LearningState:
        if not self.path.exists():
            return LearningState()
        try:
            return LearningState.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return LearningState()

    def save(self, state: LearningState) -> LearningState:
        state.updated_at = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(state.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(self.path)
        return state

    def set_status(self, doc_id: str, status: Status) -> LearningState:
        state = self.load()
        record = state.lectures.get(doc_id) or LectureProgress()
        record.status = status
        record.updated_at = _now()
        record.last_studied_at = record.updated_at
        state.lectures[doc_id] = record
        return self.save(state)

    def touch(self, doc_id: str) -> LearningState:
        state = self.load()
        record = state.lectures.get(doc_id) or LectureProgress()
        if record.status == "not_started":
            record.status = "learning"
        record.last_studied_at = _now()
        record.updated_at = record.last_studied_at
        state.lectures[doc_id] = record
        return self.save(state)

    def record_quiz(self, doc_id: str, *, correct: int, total: int) -> LearningState:
        state = self.load()
        record = state.lectures.get(doc_id) or LectureProgress()
        record.quiz_attempts += max(total, 0)
        record.quiz_correct += max(min(correct, total), 0)
        if total > 0 and record.status == "not_started":
            record.status = "learning"
        record.updated_at = _now()
        record.last_studied_at = record.updated_at
        state.lectures[doc_id] = record
        return self.save(state)

    def record_attempt(self, attempt: QuizAttempt) -> LearningState:
        state = self.load()
        if not attempt.attempt_id:
            attempt.attempt_id = uuid.uuid4().hex[:12]
        if not attempt.created_at:
            attempt.created_at = _now()
        state.attempts.append(attempt)
        # 控制体积：每讲最多保留最近 200 条
        by_lecture: dict[str, list[QuizAttempt]] = {}
        for item in state.attempts:
            by_lecture.setdefault(item.lecture_id, []).append(item)
        trimmed: list[QuizAttempt] = []
        for items in by_lecture.values():
            trimmed.extend(items[-200:])
        state.attempts = trimmed

        record = state.lectures.get(attempt.lecture_id) or LectureProgress()
        record.quiz_attempts += 1
        if attempt.correct:
            record.quiz_correct += 1
        if record.status == "not_started":
            record.status = "learning"
        record.updated_at = _now()
        record.last_studied_at = record.updated_at
        state.lectures[attempt.lecture_id] = record
        return self.save(state)

    def wrong_attempts(self, lecture_id: str | None = None, *, limit: int = 50) -> list[QuizAttempt]:
        state = self.load()
        items = [item for item in state.attempts if not item.correct]
        if lecture_id:
            items = [item for item in items if item.lecture_id == lecture_id]
        return list(reversed(items[-limit:]))

    def weak_points(self, *, limit: int = 12) -> list[WeakPoint]:
        state = self.load()
        wrong = [item for item in state.attempts if not item.correct]
        counter: Counter[tuple[str, str]] = Counter()
        pages: dict[tuple[str, str], list[int]] = {}
        for item in wrong:
            concepts = item.concepts or ["未标注概念"]
            for concept in concepts:
                key = (item.lecture_id, concept)
                counter[key] += 1
                bucket = pages.setdefault(key, [])
                for source in item.source_pages:
                    if source.page not in bucket:
                        bucket.append(source.page)
        ranked = counter.most_common(limit)
        results: list[WeakPoint] = []
        for (lecture_id, concept), count in ranked:
            sample = pages.get((lecture_id, concept), [])[:4]
            action = (
                f"回到 {lecture_id} 复习「{concept}」"
                + (f"（建议先看 p.{', '.join(map(str, sample))}）" if sample else "")
            )
            results.append(
                WeakPoint(
                    concept=concept,
                    lecture_id=lecture_id,
                    error_count=count,
                    recommended_action=action,
                    sample_pages=sample,
                )
            )
        return results

    def recent_lecture_id(self) -> str | None:
        state = self.load()
        dated = [
            (record.last_studied_at or record.updated_at, doc_id)
            for doc_id, record in state.lectures.items()
            if record.last_studied_at or record.updated_at
        ]
        if not dated:
            return None
        dated.sort(reverse=True)
        return dated[0][1]
