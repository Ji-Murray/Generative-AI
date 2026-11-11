from __future__ import annotations

from lectureqa.generation.quiz import (
    QuizGenerator,
    is_meta_question,
    is_page_locator_question,
    validate_question,
)
from lectureqa.llm import FakeLLM

KEYS = {("lecture03_rag", 2), ("lecture02_transformer", 3)}


def test_validate_question_accepts_well_formed_mcq() -> None:
    question, reason = validate_question(
        {
            "type": "mcq",
            "difficulty": "medium",
            "question": "RAG 推荐的分块重叠是多少？",
            "options": ["A. 64 tokens", "B. 256 tokens", "C. 1024 tokens", "D. 0"],
            "answer": "64 tokens",
            "explanation": "讲义写明重叠 64 tokens。",
            "sources": [{"doc_id": "lecture03_rag", "page": 2}],
        },
        KEYS,
        0,
    )
    assert reason is None
    assert question is not None
    assert question.options[0] == "64 tokens"
    assert question.answer == "A"


def test_validate_question_rejects_unsourced_question() -> None:
    question, reason = validate_question(
        {
            "type": "short_answer",
            "question": "什么是 MoE？",
            "answer": "专家混合",
            "explanation": "讲义未涵盖。",
            "sources": [{"doc_id": "lecture99", "page": 1}],
        },
        KEYS,
        0,
    )
    assert question is None
    assert reason is not None
    assert reason["reason"] == "出处不在检索证据中"


def test_validate_question_normalizes_true_false() -> None:
    question, _ = validate_question(
        {
            "type": "true_false",
            "question": "多头注意力默认 8 个头。",
            "answer": "正确",
            "explanation": "讲义写明 h = 8。",
            "sources": ["lecture02_transformer:p3"],
        },
        KEYS,
        1,
    )
    assert question is not None
    assert question.answer == "True"
    assert question.options == ["True", "False"]


def test_validate_question_rejects_mcq_with_bad_answer() -> None:
    question, reason = validate_question(
        {
            "type": "mcq",
            "question": "题干",
            "options": ["A", "B", "C"],
            "answer": "E",
            "explanation": "解释",
            "sources": [{"doc_id": "lecture03_rag", "page": 2}],
        },
        KEYS,
        0,
    )
    assert question is None
    assert reason is not None


def test_quiz_generator_keeps_grounded_and_drops_the_rest(retriever, settings, monkeypatch) -> None:
    evidence = retriever.retrieve("分块策略", top_k=4)
    payload = """```json
    {"questions": [
      {"type": "mcq", "difficulty": "easy", "question": "chunk 大小建议多少？",
       "options": ["512 tokens", "1024 tokens", "2048 tokens", "64 tokens"],
       "answer": "A", "explanation": "讲义写明 512 tokens。",
       "sources": [{"doc_id": "lecture03_rag", "page": 2}]},
      {"type": "mcq", "difficulty": "easy", "question": "无出处题",
       "options": ["A", "B", "C"], "answer": "A", "explanation": "x",
       "sources": [{"doc_id": "lecture77_none", "page": 8}]}
    ]}```"""
    llm = FakeLLM(payload)
    generator = QuizGenerator(retriever, llm, settings)
    monkeypatch.setattr(generator, "_evidence", lambda *a, **k: evidence)

    result = generator.generate("分块策略", n=2)

    assert len(result.questions) == 1
    assert result.questions[0].sources[0].doc_id == "lecture03_rag"
    assert result.dropped and result.dropped[0]["reason"] == "出处不在检索证据中"


def test_quiz_generator_refuses_without_evidence(retriever, settings) -> None:
    generator = QuizGenerator(retriever, FakeLLM("{}"), settings)
    result = generator.generate("量子退火在蛋白质折叠中的应用", n=3)
    assert result.questions == []
    assert result.dropped

def test_validate_question_rejects_lecture_title_meta() -> None:
    question, reason = validate_question(
        {
            "type": "short_answer",
            "question": "本讲的 Lecture 标题是什么？",
            "answer": "Diffusion Models",
            "explanation": "封面写了标题。",
            "sources": [{"doc_id": "lecture03_rag", "page": 2}],
        },
        KEYS,
        0,
    )
    assert question is None
    assert reason is not None
    assert "元信息" in reason["reason"]


def test_is_meta_question_detects_title_prompts() -> None:
    assert is_meta_question("这一讲叫什么名字？")
    assert is_meta_question("What is the title of Lecture 5?")
    assert not is_meta_question("扩散模型的损失函数如何推导？")

def test_validate_question_rejects_ppt_page_content_meta() -> None:
    question, reason = validate_question(
        {
            "type": "short_answer",
            "question": "PPT 第 5 页的题目是什么？",
            "answer": "扩散模型定义",
            "explanation": "第5页标题写了定义。",
            "sources": [{"doc_id": "lecture03_rag", "page": 2}],
        },
        KEYS,
        0,
    )
    assert question is None
    assert reason is not None
    assert "元信息" in reason["reason"] or "页码" in reason["reason"]


def test_validate_question_rejects_which_page_question() -> None:
    question, reason = validate_question(
        {
            "type": "mcq",
            "question": "注意力机制在哪一页介绍？",
            "options": ["第2页", "第3页", "第4页", "第5页"],
            "answer": "A",
            "explanation": "在第2页。",
            "sources": [{"doc_id": "lecture03_rag", "page": 2}],
        },
        KEYS,
        0,
    )
    assert question is None
    assert reason is not None


def test_is_meta_question_detects_page_prompts() -> None:
    assert is_meta_question("课件第10页讲了什么？")
    assert is_page_locator_question("某公式在第几页？", "第7页")
    assert not is_meta_question("扩散模型的前向过程噪声如何加入？")

