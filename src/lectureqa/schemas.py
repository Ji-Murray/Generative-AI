"""跨模块共享的数据契约。任何模块之间传递的数据都必须是这里的模型，禁止裸 dict。"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- 语料
class Chunk(BaseModel):
    """分块后的最小检索单元，1 个 chunk 只属于 1 页。"""

    chunk_id: str = Field(description="全局唯一：{doc_id}:p{page}:c{idx}")
    doc_id: str
    doc_title: str
    page: int = Field(ge=1, description="1-based 页码，用于出处跳转")
    chunk_index: int = Field(ge=0, description="页内块序号")
    text: str
    char_start: int = Field(default=0, description="在整页文本中的起始字符偏移")
    char_end: int = Field(default=0, description="在整页文本中的结束字符偏移")

    @property
    def marker(self) -> str:
        """LLM 输出中使用的引用标记：[[doc_id:p页码]]"""
        return f"[[{self.doc_id}:p{self.page}]]"


class DocumentInfo(BaseModel):
    doc_id: str
    doc_title: str
    source_path: str
    pages: int
    chunks: int


# --------------------------------------------------------------------------- 检索
class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float = Field(description="最终排序分数（越大越相关）")
    dense_score: float | None = None
    lexical_score: float | None = None
    support: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="证据支持度：问题证据在片段中的可验证覆盖程度，用于拒答判定",
    )


# --------------------------------------------------------------------------- 生成
class Citation(BaseModel):
    doc_id: str
    doc_title: str
    page: int
    chunk_id: str
    snippet: str = Field(description="证据原文摘录，用于前端展示")
    valid: bool = Field(default=True, description="该引用是否落在实际检索到的证据上")


class ExternalSource(BaseModel):
    """讲义之外的补充来源（当前来自网络），必须与课程出处分开标注。"""

    title: str
    url: str
    snippet: str
    provider: str = "web"


class Answer(BaseModel):
    question: str
    answer: str = Field(description="Markdown 正文，正文中的引用已被规范化")
    citations: list[Citation] = Field(default_factory=list)
    evidence: list[RetrievedChunk] = Field(default_factory=list)
    external_sources: list[ExternalSource] = Field(
        default_factory=list, description="非讲义来源（网络补充）；为空表示答案只依据讲义"
    )
    answer_scope: Literal["lecture", "external", "none"] = Field(
        default="lecture", description="lecture=仅讲义；external=讲义证据不足、使用网络补充；none=拒答"
    )
    grounded: bool = Field(description="是否至少有一条有效引用")
    refused: bool = Field(default=False)
    invalid_citations: list[str] = Field(default_factory=list)
    model: str = ""
    latency_ms: int = 0


class StreamEvent(BaseModel):
    kind: Literal["status", "delta", "final", "error"]
    text: str = ""
    answer: Answer | None = None


# --------------------------------------------------------------------------- Quiz
class QuestionType(StrEnum):
    mcq = "mcq"
    true_false = "true_false"
    short_answer = "short_answer"


DIFFICULTIES = ("easy", "medium", "hard")


class QuizSource(BaseModel):
    doc_id: str
    page: int


class QuizQuestion(BaseModel):
    question_id: str = ""
    type: QuestionType
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    question: str
    options: list[str] = Field(default_factory=list, description="mcq 必填，≥3 项；true_false 固定两项")
    answer: str = Field(description="mcq 为选项字母（A/B/C/D）；true_false 为 True/False；short_answer 为参考答案")
    explanation: str
    sources: list[QuizSource] = Field(default_factory=list)
    grounded: bool = True


class QuizResult(BaseModel):
    topic: str
    questions: list[QuizQuestion] = Field(default_factory=list)
    dropped: list[dict] = Field(default_factory=list, description="因不可溯源/结构非法被丢弃的题目")
    evidence: list[RetrievedChunk] = Field(default_factory=list)
    model: str = ""


# --------------------------------------------------------------------------- 评估
class TestItem(BaseModel):
    qid: str
    question: str
    type: Literal["answerable", "unanswerable"] = "answerable"
    gold_doc_ids: list[str] = Field(default_factory=list)
    gold_pages: list[int] = Field(default_factory=list)
    reference_answer: str = ""
    notes: str = ""


class ItemResult(BaseModel):
    qid: str
    question: str
    type: Literal["answerable", "unanswerable"]
    refused: bool
    hit_at_k: bool
    recall_at_k: float
    reciprocal_rank: float
    citation_precision: float
    grounded: bool
    answer: str
    latency_ms: int
    judge_score: float | None = None
    error: str = ""


class EvalReport(BaseModel):
    testset: str
    k: int
    n: int
    metrics: dict[str, float]
    items: list[ItemResult]
    generated_at: str


# --------------------------------------------------------------------------- 学习闭环
class LectureOutline(BaseModel):
    """一讲的结构化学习卡片：目标、关键概念、概要与关键页码。"""

    doc_id: str
    order: int = Field(ge=1, description="1-based 讲次顺序")
    title: str
    summary: str
    topics: list[str] = Field(
        default_factory=list,
        description="本讲脉络：形如「p.3-7 主题：一句话要点」，区间应覆盖整讲页码",
    )
    objectives: list[str] = Field(default_factory=list, description="学完这一讲应该会什么")
    concepts: list[str] = Field(default_factory=list, description="3-6 个关键概念")
    key_pages: list[int] = Field(
        default_factory=list, description="各脉络区间的起点页，便于跳转预览"
    )


class CourseOutline(BaseModel):
    """课程地图：整门课的总览 + 逐讲卡片 + 讲与讲之间的关系。"""

    course_title: str = "课程大纲"
    overview: str = ""
    learning_path: list[str] = Field(default_factory=list, description="按学习顺序排列的 doc_id")
    lectures: list[LectureOutline] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list, description="如「第2讲 → 第3讲：注意力是 RAG 的基础」")
    generated_at: str = ""
    fingerprint: str = ""

    def lecture(self, doc_id: str) -> LectureOutline | None:
        return next((item for item in self.lectures if item.doc_id == doc_id), None)


class LectureProgress(BaseModel):
    status: Literal["not_started", "learning", "completed"] = "not_started"
    updated_at: str = ""
    quiz_attempts: int = 0
    quiz_correct: int = 0
    last_studied_at: str = ""


class QuizAttempt(BaseModel):
    attempt_id: str
    lecture_id: str
    question_id: str
    question: str
    question_type: str
    student_answer: str
    correct_answer: str
    correct: bool
    explanation: str = ""
    concepts: list[str] = Field(default_factory=list)
    source_pages: list[QuizSource] = Field(default_factory=list)
    created_at: str = ""


class WeakPoint(BaseModel):
    concept: str
    lecture_id: str
    error_count: int = 0
    recommended_action: str = ""
    sample_pages: list[int] = Field(default_factory=list)


class LearningState(BaseModel):
    lectures: dict[str, LectureProgress] = Field(default_factory=dict)
    attempts: list[QuizAttempt] = Field(default_factory=list)
    updated_at: str = ""

    def status_of(self, doc_id: str) -> str:
        record = self.lectures.get(doc_id)
        return record.status if record else "not_started"
