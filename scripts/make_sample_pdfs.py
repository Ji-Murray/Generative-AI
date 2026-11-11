"""生成用于自测 / CI 的示例讲义 PDF（真实语料请放进 data/）。

用法：python scripts/make_sample_pdfs.py --out data/sample
"""

from __future__ import annotations

import argparse
from pathlib import Path

DECKS: dict[str, list[tuple[str, list[str]]]] = {
    "lecture01_course_overview": [
        (
            "DSC6021 Generative AI 课程概览",
            [
                "课程定位：面向研究生的生成式人工智能专题课。",
                "课程目标：理解生成式模型的基本原理，并能独立构建一个可演示的 AI 产品。",
                "考核方式：项目（Product）40%，技术论文 20%，平时作业 40%。",
            ],
        ),
        (
            "什么是生成式 AI",
            [
                "生成式 AI 指能够产生文本、图像、音频等新内容的模型。",
                "与传统判别式模型不同，生成式模型学习的是数据分布 P(x)。",
                "大语言模型（LLM）是当前最主流的文本生成式模型。",
            ],
        ),
        (
            "课程节奏",
            [
                "第 1-4 周：基础模型与提示工程。",
                "第 5-8 周：检索增强生成（RAG）与评估方法。",
                "第 9-12 周：多模态、智能体与产品化落地。",
            ],
        ),
    ],
    "lecture02_transformer": [
        (
            "Transformer 架构",
            [
                "Transformer 完全基于注意力机制，抛弃了循环结构，因此可以高度并行。",
                "核心组件：自注意力、前馈网络、残差连接、层归一化、位置编码。",
            ],
        ),
        (
            "缩放点积注意力",
            [
                "注意力计算公式：Attention(Q, K, V) = softmax(QK^T / sqrt(d_k)) V。",
                "缩放因子 sqrt(d_k) 用于防止点积随维度增大而方差过大，导致 softmax 梯度消失。",
                "d_k 是键向量的维度。",
            ],
        ),
        (
            "多头注意力",
            [
                "多头注意力把 Q、K、V 投影到 h 个子空间并行计算注意力。",
                "论文默认设置 h = 8 个注意力头，每个头的维度 d_k = d_model / h = 64。",
                "多头机制让模型同时关注不同位置的子空间信息。",
            ],
        ),
        (
            "位置编码",
            [
                "自注意力本身没有顺序概念，因此需要位置编码注入序列位置信息。",
                "原始论文使用正弦/余弦函数构造绝对位置编码。",
            ],
        ),
    ],
    "lecture03_retrieval_augmented_generation": [
        (
            "RAG 概述",
            [
                "检索增强生成（RAG）在生成前先检索外部知识，降低幻觉并支持溯源。",
                "RAG 的两条主干：检索管线（离线建库 + 在线召回）与生成管线（带引用的作答）。",
            ],
        ),
        (
            "分块策略",
            [
                "分块大小建议 512 tokens，重叠 64 tokens。",
                "重叠过大导致检索冗余，过小则容易切断语义。",
                "对本课程讲义这类幻灯片文档，应以「页」为不可跨越的边界。",
            ],
        ),
        (
            "向量库与混合检索",
            [
                "本地演示推荐 ChromaDB 持久化索引，零运维。",
                "只用向量检索容易漏掉精确术语，因此要配合 BM25 做混合检索。",
            ],
        ),
        (
            "RAG 的评估",
            [
                "检索侧指标：recall@k 与 MRR，衡量正确页面是否被召回以及排在第几。",
                "生成侧指标：引用精度（citation precision）与证据支持率，衡量答案是否可溯源。",
                "拒答能力同样要单独评估：不可回答的问题必须拒答而不是编造。",
            ],
        ),
    ],
}


def _write_deck(pages: list[tuple[str, list[str]]], path: Path) -> None:
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz  # type: ignore[no-redef]

    document = fitz.open()
    try:
        for title, bullets in pages:
            page = document.new_page()
            body = "\n".join(f"• {bullet}" for bullet in bullets)
            page.insert_textbox(
                fitz.Rect(56, 56, 540, 740),
                f"{title}\n\n{body}",
                fontsize=14,
                fontname="china-s",
                lineheight=1.6,
            )
        document.set_metadata({"title": path.stem, "author": "DSC6021"})
        document.save(path)
    finally:
        document.close()


def build_sample_decks(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, pages in DECKS.items():
        path = out_dir / f"{name}.pdf"
        _write_deck(pages, path)
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="生成示例讲义 PDF")
    parser.add_argument("--out", default="data/sample")
    args = parser.parse_args()
    for path in build_sample_decks(Path(args.out)):
        print(f"已生成 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
