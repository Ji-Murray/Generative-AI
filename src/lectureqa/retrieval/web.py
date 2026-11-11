"""讲义之外的网络补充检索（可选，默认关闭）。

只在讲义证据不足且调用方显式开启时使用；返回结果必须与课程出处分开标注，
不得伪装成讲义引用。
"""

from __future__ import annotations

import html
import logging
import re
import time
from typing import Protocol
from urllib.parse import quote

import httpx

from lectureqa.config import Settings
from lectureqa.retrieval.rerank import coverage_score
from lectureqa.schemas import ExternalSource
from lectureqa.textutils import has_cjk, truncate

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_PUNCT_RE = re.compile(r"[？?！!。，,、；;：:\s]+")
_INTERROGATIVE_RE = re.compile(
    r"(什么|如何|怎么|怎样|为什么|为何|哪些|哪个|哪几|多少|是否|能否|是不是|有没有)"
)
_LEAD_VERBS_RE = re.compile(r"^(实现|使用|利用|进行|完成|来|去|的|了|是|有|可以|能|会|要|想|用)+")
_TRAIL_VERBS_RE = re.compile(r"(实现|使用|利用|进行|完成|来|去|的|了|是|有|可以|能|会|要|想|用)+$")
USER_AGENT = "LectureQA/0.1 (course project)"


class WebSearch(Protocol):
    name: str

    def search(self, query: str, k: int = 3) -> list[ExternalSource]: ...


class NullWebSearch:
    """关闭状态：不发起任何网络请求，保持「证据不足即拒答」的默认行为。"""

    name = "off"

    def search(self, query: str, k: int = 3) -> list[ExternalSource]:
        return []


def _clean(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text)).strip()


class WikipediaSearch:
    """无 Key 的维基百科检索，用作可复现的网络补充来源。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.name = "wikipedia"
        self._client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.settings.web_timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            )
        return self._client

    def _lang(self, query: str) -> str:
        if self.settings.web_lang != "auto":
            return self.settings.web_lang
        return "zh" if has_cjk(query) else "en"

    def _get_json(self, api: str, params: dict) -> dict:
        """维基偶尔返回 429 / 非 JSON，重试一次；仍失败交给调用方降级。"""
        last: Exception | None = None
        for attempt in range(2):
            try:
                response = self._http().get(api, params=params)
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001 - 统一在调用方决定是否放弃
                last = exc
                if attempt == 0:
                    time.sleep(0.8)
        raise last or RuntimeError("维基检索失败")

    def _search_terms(self, query: str) -> list[str]:
        """把自然语言问题压成少量检索词，避免整句噪音把维基检索带偏。"""
        text = _PUNCT_RE.sub(" ", query).strip()
        if not text:
            return []
        candidates = []
        match = _INTERROGATIVE_RE.search(text)
        if match:
            left = _TRAIL_VERBS_RE.sub("", text[: match.start()].strip()).strip()
            right = _LEAD_VERBS_RE.sub("", text[match.end() :].strip()).strip()
            if left and right:
                candidates.append(f"{left} {right}")
            if left:
                candidates.append(left)
            elif right:
                candidates.append(right)
        candidates.append(text)

        seen: set[str] = set()
        terms: list[str] = []
        for item in candidates:
            item = " ".join(item.split())
            if item and item not in seen:
                seen.add(item)
                terms.append(item)
        return terms[:2]

    def search(self, query: str, k: int = 3) -> list[ExternalSource]:
        terms = self._search_terms(query)
        if not terms or k <= 0:
            return []
        lang = self._lang(query)
        variant = "zh-cn" if lang == "zh" else "en"
        api = f"https://{lang}.wikipedia.org/w/api.php"
        titles: list[str] = []
        snippets: dict[str, str] = {}
        for term in terms:
            try:
                found = self._get_json(
                    api,
                    {
                        "action": "query",
                        "list": "search",
                        "srsearch": term,
                        "srlimit": max(k, 3),
                        "format": "json",
                        "utf8": 1,
                        "variant": variant,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - 单个检索词失败不影响其他词
                logger.warning("网络补充检索失败（%s, %s）：%s", self.name, term, exc)
                continue
            for hit in found.get("query", {}).get("search", []):
                title = hit.get("title", "")
                if title and title not in snippets:
                    snippets[title] = _clean(hit.get("snippet", ""))
                    titles.append(title)
        if not titles:
            return []

        extracts: dict[str, str] = {}
        try:
            pages = self._get_json(
                api,
                {
                    "action": "query",
                    "prop": "extracts",
                    "exintro": 1,
                    "explaintext": 1,
                    "exlimit": "max",
                    "redirects": 1,
                    "titles": "|".join(titles[:20]),
                    "format": "json",
                    "utf8": 1,
                    "variant": variant,
                },
            )
        except Exception as exc:  # noqa: BLE001 - 摘要失败时退回搜索片段
            logger.warning("网络摘要获取失败（%s）：%s", self.name, exc)
            pages = {}
        for page in pages.get("query", {}).get("pages", {}).values():
            title = page.get("title", "")
            extract = (page.get("extract") or "").strip()
            if title and extract:
                extracts[title] = extract

        ranked: list[tuple[float, str, str]] = []
        for title in titles:
            body = extracts.get(title) or snippets.get(title, "")
            if not body:
                continue
            ranked.append((coverage_score(query, f"{title} {body}"), title, body))
        ranked.sort(key=lambda item: item[0], reverse=True)
        chosen = [item for item in ranked if item[0] >= self.settings.web_min_coverage]

        sources: list[ExternalSource] = []
        for _score, title, body in chosen[:k]:
            sources.append(
                ExternalSource(
                    title=title,
                    url=f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                    snippet=truncate(body, 600),
                    provider=self.name,
                )
            )
        return sources


def make_web_search(settings: Settings) -> WebSearch:
    if settings.web_fallback == "wikipedia":
        return WikipediaSearch(settings)
    return NullWebSearch()
