"""中文提问 → 英文课件检索改写。

讲义多为英文，中文问句与原文几乎没有词面重叠：BM25 / 覆盖度会直接归零。
此处先做术语表扩展，必要时再用 LLM 产出英文检索查询；回答仍用原问题（中文作答）。
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

from lectureqa.textutils import has_cjk

logger = logging.getLogger(__name__)

# 长词优先，避免「神经网络」抢先吃掉「图神经网络」
_TERM_GLOSSARY: tuple[tuple[str, str], ...] = (
    ("图神经网络", "graph neural network GNN"),
    ("卷积神经网络", "convolutional neural network CNN"),
    ("几何深度学习", "geometric deep learning"),
    ("自注意力", "self-attention"),
    ("多头注意力", "multi-head attention"),
    ("注意力机制", "attention mechanism"),
    ("扩散模型", "diffusion model"),
    ("变分自编码器", "variational autoencoder VAE"),
    ("生成对抗网络", "generative adversarial network GAN"),
    ("强化学习", "reinforcement learning RL"),
    ("人类反馈", "human feedback RLHF"),
    ("检索增强", "retrieval augmented generation RAG"),
    ("向量数据库", "vector database"),
    ("嵌入", "embedding"),
    ("编码器", "encoder"),
    ("解码器", "decoder"),
    ("变换器", "transformer"),
    ("Transformer", "transformer"),
    ("神经网络", "neural network"),
    ("卷积", "convolution CNN convolutional conv"),
    ("残差", "residual"),
    ("池化", "pooling"),
    ("归一化", "normalization"),
    ("损失函数", "loss function"),
    ("梯度", "gradient"),
    ("反向传播", "backpropagation"),
    ("过拟合", "overfitting"),
    ("正则化", "regularization"),
    ("贝叶斯", "Bayesian"),
    ("概率图", "probabilistic graphical"),
    ("高斯过程", "Gaussian process"),
    ("隐马尔可夫", "hidden Markov HMM"),
    ("最大似然", "maximum likelihood"),
    ("交叉熵", "cross entropy"),
    ("蒸馏", "distillation"),
    ("微调", "fine-tuning"),
    ("预训练", "pretraining"),
    ("大语言模型", "large language model LLM"),
    ("提示词", "prompt"),
    ("幻觉", "hallucination"),
    ("引用", "citation"),
    ("课件", "lecture slides"),
    ("讲义", "lecture notes"),
)

_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_\-']{1,}|\d+(?:\.\d+)?")

_REWRITE_SYSTEM = (
    "你是检索查询改写器。用户会用中文（或中英混排）提问，"
    "课程讲义是英文。请把问题改写成适合在英文课件中检索的英文查询。\n"
    "要求：只输出一行英文，保留专有名词缩写（CNN、GNN、Transformer 等），"
    "不要解释、不要标点装饰、不要引号。"
)


class _Completer(Protocol):
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str: ...


def lexical_expand(query: str) -> str:
    """中文提问时追加英文术语，兼容英文课件与中文示例语料。

    保留原问句（中文 BM25 仍可用），并挂上术语表英文词（英文课件词面可命中）。
    """
    text = (query or "").strip()
    if not text or not has_cjk(text):
        return text
    extras: list[str] = []
    lowered = text.lower()
    for zh, en in _TERM_GLOSSARY:
        hit = zh.lower() in lowered if zh.isascii() else zh in text
        if hit:
            extras.append(en)
    if not extras:
        return text
    return f"{text} {' '.join(dict.fromkeys(extras))}"


def _llm_english_query(question: str, llm: _Completer) -> str | None:
    try:
        raw = llm.complete(
            [
                {"role": "system", "content": _REWRITE_SYSTEM},
                {"role": "user", "content": question},
            ],
            temperature=0.0,
            max_tokens=80,
        )
    except Exception as exc:  # noqa: BLE001 - 改写失败时退回术语表
        logger.warning("检索改写失败（%s），仅用术语表扩展", exc)
        return None
    line = (raw or "").strip().splitlines()[0].strip().strip("\"'`")
    if not line or has_cjk(line):
        return None
    return line


def rewrite_for_retrieval(query: str, llm: _Completer | None = None) -> str:
    """生成用于检索的查询：英文课件 + 中文提问时扩写/翻译；原问题仍用于作答。"""
    text = (query or "").strip()
    if not text:
        return text
    if not has_cjk(text):
        return text
    expanded = lexical_expand(text)
    if llm is None:
        return expanded
    english = _llm_english_query(text, llm)
    if not english:
        return expanded
    # 英文改写 + 术语表英文词，去掉纯中文原句以免污染 BM25
    glossary_en = []
    for zh, en in _TERM_GLOSSARY:
        if zh in text:
            glossary_en.append(en)
    latin = " ".join(_LATIN.findall(text))
    return " ".join(part for part in [english, " ".join(glossary_en), latin] if part).strip()
