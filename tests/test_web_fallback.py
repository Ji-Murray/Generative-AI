from __future__ import annotations

from lectureqa.generation.qa import Answerer
from lectureqa.llm import FakeLLM
from lectureqa.schemas import ExternalSource


class FakeWebSearch:
    name = "fake-web"

    def __init__(self, sources: list[ExternalSource]) -> None:
        self.sources = sources
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, k: int = 3) -> list[ExternalSource]:
        self.queries.append((query, k))
        return self.sources[:k]


def _sources() -> list[ExternalSource]:
    return [
        ExternalSource(
            title="Topological quantum error correction",
            url="https://example.org/topological",
            snippet="拓扑纠错利用任意子（anyons）的编织来实现容错量子计算。",
            provider="fake-web",
        )
    ]


def test_web_disabled_keeps_refusal_and_skips_llm(retriever, settings) -> None:
    llm = FakeLLM("不应被调用")
    web = FakeWebSearch(_sources())
    answer = Answerer(retriever, llm, settings, web_search=web).answer(
        "量子计算机如何实现拓扑纠错？", allow_web=False
    )

    assert answer.refused is True
    assert answer.answer_scope == "none"
    assert answer.external_sources == []
    assert web.queries == []
    assert llm.calls == []


def test_web_fallback_marks_external_sources(retriever, settings) -> None:
    llm = FakeLLM("拓扑纠错利用任意子的编织实现容错量子计算 [[web:1]]。")
    web = FakeWebSearch(_sources())
    answer = Answerer(retriever, llm, settings, web_search=web).answer(
        "量子计算机如何实现拓扑纠错？", allow_web=True
    )

    assert answer.refused is False
    assert answer.answer_scope == "external"
    assert answer.grounded is False
    assert answer.citations == []
    assert len(answer.external_sources) == 1
    assert answer.external_sources[0].url == "https://example.org/topological"
    assert web.queries


def test_external_answer_rejects_unverifiable_markers(retriever, settings) -> None:
    llm = FakeLLM("答案 [[web:9]]")
    answer = Answerer(
        retriever, llm, settings, web_search=FakeWebSearch(_sources())
    ).answer("量子计算机如何实现拓扑纠错？", allow_web=True)

    assert answer.refused is True
    assert answer.answer_scope == "none"
    assert answer.external_sources == []


def test_external_answer_strips_lecture_markers(retriever, settings) -> None:
    llm = FakeLLM("网络结论 [[web:1]]，另见讲义 [[lecture02_transformer:p2]]。")
    answer = Answerer(
        retriever, llm, settings, web_search=FakeWebSearch(_sources())
    ).answer("量子计算机如何实现拓扑纠错？", allow_web=True)

    assert answer.refused is False
    assert answer.answer_scope == "external"
    assert len(answer.external_sources) == 1
    assert "lecture02_transformer" not in answer.answer
    assert answer.invalid_citations == ["[[lecture02_transformer:p2]]"]


def test_external_answer_strips_literal_doc_id_lecture_markers(retriever, settings) -> None:
    llm = FakeLLM("网络结论 [[web:1]]，另见讲义 [[doc_id:lecture02_transformer:p2]]。")
    answer = Answerer(
        retriever, llm, settings, web_search=FakeWebSearch(_sources())
    ).answer("量子计算机如何实现拓扑纠错？", allow_web=True)

    assert answer.refused is False
    assert "lecture02_transformer" not in answer.answer
    assert "doc_id" not in answer.answer
    assert answer.invalid_citations == ["[[doc_id:lecture02_transformer:p2]]"]


def test_web_fallback_after_lecture_no_answer(retriever, settings) -> None:
    llm = FakeLLM(["NO_ANSWER", "网络答案 [[web:1]]"])
    answer = Answerer(
        retriever, llm, settings, web_search=FakeWebSearch(_sources())
    ).answer("多头注意力默认使用多少个注意力头？", allow_web=True)

    assert answer.answer_scope == "external"
    assert answer.refused is False
    assert answer.citations == []
    assert len(answer.external_sources) == 1


def test_web_fallback_follows_settings_when_flag_unspecified(retriever, settings) -> None:
    enabled = settings.model_copy(update={"web_fallback": "wikipedia"})
    llm = FakeLLM("网络结论 [[web:1]]")
    web = FakeWebSearch(_sources())
    answer = Answerer(retriever, llm, enabled, web_search=web).answer(
        "量子计算机如何实现拓扑纠错？"
    )

    assert answer.answer_scope == "external"
    assert web.queries
