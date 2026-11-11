"""与语言无关的文本工具：分词、断句、归一化。

课程讲义中英混排，这里的分词策略是：
- 拉丁字母/数字：按词切，转小写
- CJK 字符：单字 + 二元组（不引入 jieba 之类重依赖，且对 BM25 / 哈希向量足够）
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x3040, 0x30FF),
    (0xAC00, 0xD7AF),
)

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-']*|\d+(?:\.\d+)?")
_CJK_CHAR = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")

# 断句：中英文句末标点 + 换行；不切小数点/常见缩写
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])|(?<=[.])\s+|(?<=\n)")

STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "is", "are", "was", "were",
    "for", "with", "as", "by", "at", "from", "that", "this", "it", "be", "what", "which",
    "how", "why", "when", "who", "does", "do", "did", "can", "could", "should", "would",
    "的", "了", "是", "在", "和", "与", "及", "或", "中", "对", "有", "为", "被", "把",
    "吗", "呢", "什么", "如何", "怎么", "为什么", "哪", "哪些", "一下", "请", "讲", "说",
}


def is_cjk(char: str) -> bool:
    code = ord(char)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def has_cjk(text: str) -> bool:
    return any(is_cjk(char) for char in text)


def normalize_ws(text: str) -> str:
    """统一换行、压缩行内空白，保留段落分隔。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tokenize(text: str) -> list[str]:
    """返回用于 BM25 / 哈希向量的词元列表（保留重复，调用方自行决定是否去重）。"""
    text = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = [m.group(0) for m in _LATIN_WORD.finditer(text)]
    for match in _CJK_CHAR.finditer(text):
        tokens.append(match.group(0))
    # CJK 二元组：提升「神经网络」这类术语的区分度
    cjk_chars = [m.group(0) for m in _CJK_CHAR.finditer(text)]
    tokens.extend("".join(cjk_chars[i : i + 2]) for i in range(len(cjk_chars) - 1))
    return tokens


def content_tokens(text: str) -> list[str]:
    """去掉停用词与单字符标点噪音，用于证据覆盖度计算。"""
    return [t for t in tokenize(text) if t not in STOPWORDS and len(t.strip()) > 0]


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    return [p for p in parts if p]


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    if not text:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        return f"doc-{digest}"
    return text[:max_len].strip("-")


def truncate(text: str, max_chars: int = 320) -> str:
    text = normalize_ws(text).replace("\n", " ")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


_SAMPLE_DOC_RE = re.compile(r"^lecture\d+[-_]", re.IGNORECASE)
_EXACT_DOC_RE = re.compile(r"^(?:lecture|lec)_?0*(\d+)$", re.IGNORECASE)
_TITLE_NUM_RE = re.compile(
    r"(?:Lecture|Lec|课|讲)\s*[-_]?\s*0*(\d+)|第\s*0*(\d+)\s*讲",
    re.IGNORECASE,
)


def is_sample_lecture(doc_id: str) -> bool:
    """示例课件形如 lecture02-transformer / lecture02_transformer；正式为 lecture5。"""
    return bool(_SAMPLE_DOC_RE.match((doc_id or "").strip()))


def extract_lecture_number(*parts: str) -> int | None:
    """从 doc_id / 文件名 / 标题提取讲次编号。"""
    for part in parts:
        text = (part or "").strip()
        if not text:
            continue
        stem = text.rsplit("/", 1)[-1]
        if stem.lower().endswith(".pdf"):
            stem = stem[:-4]
        # lecture5 / Lecture5
        exact = _EXACT_DOC_RE.match(stem)
        if exact:
            return int(exact.group(1))
        # lecture02-transformer / lecture02_transformer → 2（示例）
        sample = re.match(r"^lecture_?0*(\d+)[-_]", stem, re.IGNORECASE)
        if sample:
            return int(sample.group(1))
        titled = _TITLE_NUM_RE.search(stem.replace("_", " "))
        if titled:
            return int(next(group for group in titled.groups() if group))
    return None


def lecture_sort_key(*parts: str) -> tuple[int, int, str]:
    """正式讲义按讲次排；示例课件（lecture02-xxx）放后面，避免占掉「第N讲」。"""
    doc_id = parts[0] if parts else ""
    number = extract_lecture_number(*parts)
    sample = is_sample_lecture(doc_id)
    blob = " ".join(part for part in parts if part).lower()
    if number is None:
        return (2, 10_000, blob)
    # 0=正式讲义，1=示例课件
    return (1 if sample else 0, number, blob)
