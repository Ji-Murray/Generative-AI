from __future__ import annotations

from lectureqa.generation.qa import Answerer, refusal_text
from lectureqa.llm import FakeLLM, LLMError


def test_answer_grounds_on_retrieved_evidence(retriever, settings) -> None:
    llm = FakeLLM("论文默认设置 h = 8 个注意力头 [[lecture02_transformer:p3]]。")
    answer = Answerer(retriever, llm, settings).answer("多头注意力默认使用多少个注意力头？")

    assert answer.refused is False
    assert answer.grounded is True
    assert {citation.chunk_id for citation in answer.citations} == {"lecture02_transformer:p3:c0"}
    assert "[[lecture02_transformer:p3]]" in answer.answer
    assert answer.evidence


def test_fabricated_citation_is_stripped_and_flagged(retriever, settings) -> None:
    llm = FakeLLM("分块大小 512 tokens [[lecture03_rag:p2]]，另见 [[lecture99_ghost:p1]]。")
    answer = Answerer(retriever, llm, settings).answer("分块大小和 overlap 是多少？")

    assert answer.grounded is True
    assert answer.invalid_citations == ["[[lecture99_ghost:p1]]"]
    assert "ghost" not in answer.answer


def test_no_answer_sentinel_triggers_refusal(retriever, settings) -> None:
    llm = FakeLLM("NO_ANSWER")
    answer = Answerer(retriever, llm, settings).answer("多头注意力默认使用多少个注意力头？")
    assert answer.refused is True
    assert answer.answer == refusal_text("多头注意力默认使用多少个注意力头？")


def test_low_support_short_circuits_without_calling_llm(retriever, settings) -> None:
    llm = FakeLLM("不应被调用")
    answer = Answerer(retriever, llm, settings).answer("量子计算机如何实现拓扑纠错？")
    assert answer.refused is True
    assert llm.calls == []


def test_unanswerable_question_refuses_in_english(retriever, settings) -> None:
    llm = FakeLLM("should not be used")
    answer = Answerer(retriever, llm, settings).answer("How does quantum error correction work?")
    assert answer.refused is True
    assert answer.answer == refusal_text("How does quantum error correction work?")


def test_stream_emits_deltas_then_final(retriever, settings) -> None:
    llm = FakeLLM("分块建议 512 tokens [[lecture03_rag:p2]]。")
    events = list(Answerer(retriever, llm, settings).stream_answer("分块大小建议是多少？"))

    kinds = [event.kind for event in events]
    assert "status" in kinds
    assert "delta" in kinds
    assert kinds[-1] == "final"
    assert kinds.index("status") < kinds.index("delta")
    assert events[-1].answer is not None
    assert events[-1].answer.grounded is True


class _StreamFailLLM(FakeLLM):
    """流式接口失败（例如上游内容安全拦截），一次性接口正常。"""

    def stream(self, messages, **kwargs):
        raise LLMError("Output data may contain inappropriate content.")
        yield ""  # noqa: W0101 - 保证签名仍为生成器


def test_stream_failure_falls_back_to_complete(retriever, settings) -> None:
    llm = _StreamFailLLM("论文默认设置 h = 8 个注意力头 [[lecture02_transformer:p3]]。")
    events = list(Answerer(retriever, llm, settings).stream_answer("多头注意力默认使用多少个注意力头？"))

    assert events[-1].kind == "final"
    assert events[-1].answer is not None
    assert events[-1].answer.grounded is True


class _AllFailLLM(FakeLLM):
    def complete(self, messages, **kwargs):
        raise LLMError("Output data may contain inappropriate content.")

    def stream(self, messages, **kwargs):
        raise LLMError("Output data may contain inappropriate content.")
        yield ""  # noqa: W0101


def test_stream_total_failure_yields_friendly_error(retriever, settings) -> None:
    llm = _AllFailLLM("nope")
    events = list(Answerer(retriever, llm, settings).stream_answer("多头注意力默认使用多少个注意力头？"))

    assert events[-1].kind == "error"
    assert "内容安全过滤" in events[-1].text
    assert "inappropriate content" not in events[-1].text
