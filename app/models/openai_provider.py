"""OpenAI-compatible model provider adapter (OpenAI, Ollama, vLLM, Azure)."""

import json
from typing import Any
import httpx

from app.core.errors import ProviderError
from app.core.logging import logger
from app.core.settings import settings
from app.models.base import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelUsage,
    ToolCallRequest,
)
from app.models.provider import ModelProvider


class OpenAICompatibleProvider(ModelProvider):
    """Adapter for OpenAI and OpenAI-compatible REST endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        provider_name: str = "openai",
    ) -> None:
        self._name = provider_name
        default_key = (
            "ollama" if provider_name == "ollama"
            else ("lmstudio" if provider_name == "lmstudio" else (settings.OPENAI_API_KEY or "dummy-key"))
        )
        self._api_key = api_key or default_key
        default_base_url = (
            "http://127.0.0.1:11434/v1" if provider_name == "ollama"
            else ("http://127.0.0.1:1234/v1" if provider_name == "lmstudio" else settings.OPENAI_BASE_URL)
        )
        self._base_url = (base_url or default_base_url).rstrip("/")
        self._model_name = model_name or settings.OPENAI_MODEL_NAME

    @property
    def name(self) -> str:
        return self._name

    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        converted = []
        for msg in messages:
            role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            item: dict[str, Any] = {"role": role_val, "content": msg.content or ""}
            if msg.name:
                item["name"] = msg.name
            if msg.tool_call_id:
                item["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments) if isinstance(tc.arguments, dict) else str(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            converted.append(item)
        return converted

    def _convert_tools(self, tools: list[Any] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    async def generate(self, request: ModelRequest) -> ModelResponse:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": request.selected_model or self._model_name,
            "messages": self._convert_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }

        converted_tools = self._convert_tools(request.tools)
        if converted_tools:
            payload["tools"] = converted_tools
            payload["tool_choice"] = "auto"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code >= 400:
                    raise ProviderError(
                        f"Provider {self._name} returned status {response.status_code}: {response.text}",
                        details={"status_code": response.status_code, "body": response.text},
                    )

                data = response.json()
                choice = data["choices"][0]
                message = choice["message"]
                finish_reason = choice.get("finish_reason", "stop")

                tool_calls: list[ToolCallRequest] = []
                if message.get("tool_calls"):
                    for tc in message["tool_calls"]:
                        fn = tc["function"]
                        try:
                            args = json.loads(fn.get("arguments", "{}"))
                        except Exception:
                            args = {}
                        tool_calls.append(
                            ToolCallRequest(
                                id=tc.get("id", ""),
                                name=fn.get("name", ""),
                                arguments=args,
                            )
                        )

                usage_data = data.get("usage", {})
                usage = ModelUsage(
                    prompt_tokens=usage_data.get("prompt_tokens", 0),
                    completion_tokens=usage_data.get("completion_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                )

                return ModelResponse(
                    content=message.get("content"),
                    tool_calls=tool_calls,
                    usage=usage,
                    finish_reason="tool_calls" if tool_calls else ("stop" if finish_reason == "stop" else finish_reason),
                )
        except httpx.RequestError as e:
            logger.error(f"HTTP request to model provider failed: {e}")
            raise ProviderError(f"Connection to provider {self._name} failed: {e}")
