"""LLM 访问层：OpenAI 兼容接口的唯一出口。

设计要点：
- 所有 provider 差异都被 base_url 吸收，换模型只改 .env
- 重试、JSON 修复重试、超时都在这里做，上层模块不处理网络异常
- FakeLLM 提供同一接口，用于单测与无 Key 演示
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any, Protocol

from lectureqa.config import Settings


class LLMError(RuntimeError):
    pass


def format_llm_error(message: str) -> str:
    """把上游（尤其是内容安全）错误翻译成用户能理解、可行动的中文提示。"""
    text = message.lower()
    if "inappropriate content" in text or "content_filter" in text:
        return "上游模型的内容安全过滤拦截了本次回答（通常是误判）。请换个问法或重新发送。"
    if "timeout" in text or "timed out" in text:
        return (
            "上游模型响应超时（当前 LLM_TIMEOUT 可能偏短，或模型开启了深度思考）。"
            "请稍后重试；出题/长总结可把 .env 里 LLM_TIMEOUT 调到 180+。"
        )
    return message


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """从可能夹带解释文字/markdown 围栏的输出中抠出 JSON 对象。"""
    candidate = text.strip()
    fenced = _JSON_FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("模型输出中未找到 JSON 对象") from None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"模型输出的 JSON 无法解析: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("模型输出的 JSON 顶层不是对象")
    return parsed


class LLM(Protocol):
    model: str

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str: ...

    def stream(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]: ...


class LLMClient:
    """OpenAI 兼容 chat completions 客户端（DeepSeek / Moonshot / Qwen / GPT 均可）。"""

    def __init__(self, settings: Settings, *, max_attempts: int = 3) -> None:
        self.settings = settings
        self.model = settings.llm_model
        self.max_attempts = max_attempts
        self._client: Any | None = None

    def _sdk(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            # connect 短、read 长：出题/长回答常超过默认 60s
            timeout = self.settings.llm_timeout
            try:
                import httpx

                timeout = httpx.Timeout(timeout, connect=20.0)
            except Exception:  # noqa: BLE001
                pass
            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
                timeout=timeout,
            )
        return self._client

    def _ensure_configured(self) -> None:
        if not self.settings.llm_configured:
            raise LLMError("未配置 LLM_API_KEY：请复制 .env.example 为 .env 并填入密钥")

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        self._ensure_configured()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
            "max_tokens": self.settings.llm_max_tokens if max_tokens is None else max_tokens,
        }
        if extra_body:
            payload["extra_body"] = extra_body
        elif json_mode:
            # JSON 结构化任务默认关思考，避免 Qwen3 等模型拖到超时
            payload["extra_body"] = {"enable_thinking": False}
        attempt = 0
        while True:
            attempt += 1
            try:
                kwargs = dict(payload)
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                response = self._sdk().chat.completions.create(**kwargs)
                return (response.choices[0].message.content or "").strip()
            except Exception as exc:  # noqa: BLE001 - SDK 异常类型因 provider 而异
                if json_mode and "response_format" in str(exc):
                    json_mode = False
                    attempt -= 1
                    continue
                if attempt >= self.max_attempts:
                    raise LLMError(f"LLM 调用失败（已重试 {self.max_attempts} 次）: {exc}") from exc
                time.sleep(min(2 ** (attempt - 1), 8))

    def stream(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        self._ensure_configured()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
            "max_tokens": self.settings.llm_max_tokens if max_tokens is None else max_tokens,
            "stream": True,
        }
        if extra_body:
            payload["extra_body"] = extra_body
        try:
            chunks = self._sdk().chat.completions.create(**payload)
            for event in chunks:
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
                    yield text
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"LLM 流式调用失败: {exc}") from exc

    def complete_json(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        repair_attempts: int = 1,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """要求模型返回 JSON；解析失败时把错误回灌给模型让它自我修复。"""
        convo = list(messages)
        for attempt in range(repair_attempts + 1):
            raw = self.complete(
                convo,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=True,
                extra_body=extra_body,
            )
            try:
                return extract_json(raw)
            except LLMError as exc:
                if attempt >= repair_attempts:
                    raise
                convo = [
                    *convo,
                    {"role": "assistant", "content": raw[:2000]},
                    {
                        "role": "user",
                        "content": f"上面的输出不是合法 JSON（{exc}）。请只输出一个 JSON 对象，不要任何解释。",
                    },
                ]
        raise LLMError("JSON 修复重试耗尽")  # pragma: no cover


class FakeLLM:
    """测试替身：按顺序消费预设回复，用完后重复最后一条。"""

    def __init__(
        self,
        responses: Sequence[str] | str,
        *,
        model: str = "fake-llm",
        handler: Callable[[Sequence[dict[str, str]]], str] | None = None,
    ) -> None:
        if isinstance(responses, str):
            responses = [responses]
        self._responses = list(responses)
        self._handler = handler
        self._calls = 0
        self.model = model
        self.calls: list[list[dict[str, str]]] = []

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        self.calls.append(list(messages))
        if self._handler is not None:
            return self._handler(messages)
        if not self._responses:
            return "NO_ANSWER"
        self._calls += 1
        index = min(self._calls - 1, len(self._responses) - 1)
        return self._responses[index]

    def stream(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        text = self.complete(
            messages, temperature=temperature, max_tokens=max_tokens, extra_body=extra_body
        )
        step = max(1, len(text) // 4 or 1)
        for i in range(0, len(text), step):
            yield text[i : i + step]

    def complete_json(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        repair_attempts: int = 1,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return extract_json(
            self.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_body=extra_body,
            )
        )


def make_llm(settings: Settings) -> LLMClient:
    return LLMClient(settings)
