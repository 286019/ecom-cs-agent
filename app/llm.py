"""OpenAI 兼容接口的最小客户端：httpx 直连，流式文本 + 原生 tool calls。

不依赖 openai SDK，任何兼容 /chat/completions 的服务都能用。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger("ecom.llm")


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.endpoint = f"{settings.base_url}/chat/completions"

    async def stream_turn(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """流式执行一轮模型调用。

        依次 yield ("text", 增量文本)，结束时 yield ("tool_calls", [调用列表])。
        """
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "stream": True,
            "temperature": self.settings.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(connect=10.0, read=self.settings.request_timeout, write=30.0, pool=10.0)
        calls: dict[int, dict] = {}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "ignore")[:500]
                        raise LLMError(f"HTTP {response.status_code}: {body}")

                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}

                        content = delta.get("content")
                        if content:
                            yield ("text", content)

                        for tool_delta in delta.get("tool_calls") or []:
                            index = tool_delta.get("index", 0)
                            slot = calls.setdefault(
                                index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                            )
                            if tool_delta.get("id"):
                                slot["id"] = tool_delta["id"]
                            function = tool_delta.get("function") or {}
                            if function.get("name"):
                                slot["function"]["name"] += function["name"]
                            if function.get("arguments"):
                                slot["function"]["arguments"] += function["arguments"]
        except httpx.HTTPError as exc:
            raise LLMError(f"网络请求失败：{exc}") from exc

        ordered = [calls[i] for i in sorted(calls)]
        for i, call in enumerate(ordered):
            if not call["id"]:
                call["id"] = f"call_{i}"
        yield ("tool_calls", ordered)
