from __future__ import annotations

from lectureqa.retrieval.query_rewrite import lexical_expand, rewrite_for_retrieval


def test_lexical_expand_adds_english_terms_for_cjk() -> None:
    expanded = lexical_expand("卷积神经网络和图神经网络有什么区别？")
    assert "CNN" in expanded
    assert "GNN" in expanded
    assert "convolutional" in expanded.lower()
    assert "卷积" in expanded  # 保留中文，兼容中文语料


def test_coverage_prefers_matching_script() -> None:
    from lectureqa.retrieval.rerank import coverage_score

    query = lexical_expand("卷积神经网络是什么")
    english_slide = "CNN Architecture – The conv layer is a primitive"
    chinese_slide = "卷积神经网络是一种常用的特征提取结构"
    assert coverage_score(query, english_slide) >= 0.35
    assert coverage_score(query, chinese_slide) >= 0.3


def test_lexical_expand_leaves_english_unchanged() -> None:
    query = "What is a diffusion model?"
    assert lexical_expand(query) == query


def test_rewrite_for_retrieval_uses_llm_english_when_available() -> None:
    class FakeLLM:
        def complete(self, messages, *, temperature=None, max_tokens=None) -> str:
            return "difference between CNN and GNN"

    rewritten = rewrite_for_retrieval("卷积和 GNN 的区别", llm=FakeLLM())
    assert "CNN" in rewritten or "cnn" in rewritten.lower()
    assert "GNN" in rewritten
    assert "卷积" not in rewritten


def test_rewrite_falls_back_to_glossary_without_llm() -> None:
    rewritten = rewrite_for_retrieval("扩散模型是什么")
    assert "diffusion" in rewritten.lower()
