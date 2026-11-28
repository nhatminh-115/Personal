"""Dynamic model and local provider discovery service for Kuractus."""

import json
import re
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import httpx
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.core.settings import settings
from app.models.openai_provider import OpenAICompatibleProvider
from app.models.router import ModelRouter, model_router
from app.models.routing_policy import ProviderMetadata

_SENSITIVE_PROVIDER_URL_QUERY_NAMES = {
    "key", "apikey", "xapikey", "accesskey", "clientkey", "privatekey", "secretkey",
    "token", "accesstoken", "refreshtoken", "auth", "authorization", "password", "passwd",
    "secret", "clientsecret", "credential", "credentials", "bearer", "jwt", "sig", "signature",
    "code", "ticket", "session", "sessionid",
}
_SENSITIVE_PROVIDER_URL_QUERY_PARTS = {
    "token", "secret", "password", "passwd", "authorization", "credential", "credentials",
    "bearer", "jwt", "sig", "signature", "ticket", "session",
}

MAX_PROVIDER_JSON_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CAPABILITY_PROBE_RESPONSE_BYTES = 256 * 1024
MAX_DISCOVERED_MODELS = 256
MAX_RUNTIME_CAPABILITIES = 64
MAX_RUNTIME_CAPABILITY_CHARS = 128
MAX_MODEL_ID_CHARS = 256


class ModelEntry(BaseModel):
    """Normalized descriptor of an individual model."""

    id: str
    label: str
    capabilities: List[str] = Field(default_factory=list)
    tool_support: Literal["supported", "unsupported", "unknown"] = "unknown"
    context_window: Optional[int] = None
    reasoning_support: Literal["instant", "low", "medium", "high", "max", "fixed_by_model", "unsupported", "unknown"] = "unknown"
    vision_support: Optional[bool] = None
    structured_output_support: Optional[bool] = None


class ProviderEntry(BaseModel):
    """Normalized descriptor of a model provider."""

    id: str
    label: str
    kind: Literal["local", "cloud"]
    available: bool
    base_url: str
    models: List[ModelEntry] = Field(default_factory=list)
    privacy_status: Literal["local", "cloud", "airgap"] = "local"


class ModelCatalogResponse(BaseModel):
    """Response payload for GET /v1/models."""

    providers: List[ProviderEntry]


class CapabilityProbeResult(BaseModel):
    """Result of user-triggered model capability probe."""

    provider_id: str
    model_id: str
    tool_support: Literal["supported", "unsupported", "unknown"]
    details: str


def public_provider_base_url(base_url: str) -> str:
    """Hide URL credentials in public model-catalog metadata without changing router config."""
    if not isinstance(base_url, str) or not base_url:
        return ""

    try:
        parsed = urlsplit(base_url)
    except ValueError:
        return ""

    # Provider endpoints are expected to be absolute URLs. Fail closed for malformed
    # or non-URL values rather than reflecting an opaque credential-bearing string.
    if not parsed.netloc:
        return ""

    safe_netloc = parsed.netloc.rsplit("@", 1)[-1]
    if not safe_netloc:
        return ""

    safe_query = []
    for name, value in parse_qsl(parsed.query, keep_blank_values=True):
        parts = re.findall(r"[a-z0-9]+", name.lower())
        normalized = "".join(parts)
        sensitive = (
            normalized in _SENSITIVE_PROVIDER_URL_QUERY_NAMES
            or any(part in _SENSITIVE_PROVIDER_URL_QUERY_PARTS for part in parts)
            or (len(parts) > 1 and parts[-1] == "key")
        )
        safe_query.append((name, "[REDACTED]" if sensitive else value))

    return urlunsplit((parsed.scheme, safe_netloc, parsed.path, urlencode(safe_query), ""))


def extract_runtime_tool_capability(raw_model: Dict[str, Any]) -> Optional[Literal["supported", "unsupported"]]:
    """Extract explicit tool capability metadata reported by local runtime, when available."""
    recognized = ("tools", "tool_calls", "function_calling", "functions")

    def classify(value: Any) -> Optional[Literal["supported", "unsupported"]]:
        if isinstance(value, list):
            values = {str(item).lower() for item in value[:MAX_RUNTIME_CAPABILITIES]}
            if any(name in values for name in recognized):
                return "supported"
        elif isinstance(value, dict):
            if any(value.get(name) is True for name in recognized):
                return "supported"
            if any(value.get(name) is False for name in recognized):
                return "unsupported"
        return None

    explicit = classify(raw_model.get("capabilities"))
    if explicit is not None:
        return explicit

    if raw_model.get("tools") is True or raw_model.get("tool_calls") is True:
        return "supported"
    if raw_model.get("tools") is False or raw_model.get("tool_calls") is False:
        return "unsupported"

    details = raw_model.get("details")
    if isinstance(details, dict):
        return classify(details.get("capabilities"))
    return None


def infer_tool_support(model_id: str) -> Literal["supported", "unsupported", "unknown"]:
    """Conservative fallback: returns unknown without model-name regex heuristics."""
    return "unknown"


def extract_runtime_capabilities(raw_model: Dict[str, Any]) -> List[str]:
    """Return a bounded list of capability names explicitly reported by the provider."""
    value = raw_model.get("capabilities")
    if isinstance(value, list):
        return [
            item[:MAX_RUNTIME_CAPABILITY_CHARS]
            for item in value[:MAX_RUNTIME_CAPABILITIES]
            if isinstance(item, str)
        ]
    if isinstance(value, dict):
        return [
            key[:MAX_RUNTIME_CAPABILITY_CHARS]
            for key, enabled in list(value.items())[:MAX_RUNTIME_CAPABILITIES]
            if isinstance(key, str) and enabled is True
        ]
    details = raw_model.get("details")
    if isinstance(details, dict):
        nested = details.get("capabilities")
        if isinstance(nested, list):
            return [
                item[:MAX_RUNTIME_CAPABILITY_CHARS]
                for item in nested[:MAX_RUNTIME_CAPABILITIES]
                if isinstance(item, str)
            ]
        if isinstance(nested, dict):
            return [
                key[:MAX_RUNTIME_CAPABILITY_CHARS]
                for key, enabled in list(nested.items())[:MAX_RUNTIME_CAPABILITIES]
                if isinstance(key, str) and enabled is True
            ]
    return []


async def _request_bounded_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_bytes: int,
    **kwargs: Any,
) -> Tuple[int, Any | None]:
    """Read a provider JSON response with a decoded-body byte limit."""
    async with client.stream(method, url, **kwargs) as response:
        status_code = response.status_code
        if status_code != 200:
            return status_code, None

        body = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=65536):
            if len(body) + len(chunk) > max_bytes:
                return status_code, None
            body.extend(chunk)

        try:
            return status_code, json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return status_code, None


class ModelDiscoveryService:
    """Discovers and registers local (Ollama, LM Studio) and cloud model providers."""

    def __init__(self) -> None:
        self._probed_cache: Dict[str, Literal["supported", "unsupported", "unknown"]] = {}

    def _resolve_tool_support(
        self,
        cache_key: str,
        raw_model: Dict[str, Any],
    ) -> Literal["supported", "unsupported", "unknown"]:
        """
        Priority order for tool capability classification:
        1. Explicit capability metadata reported by the local runtime, when available
        2. Successful / verified explicit capability probe
        3. Otherwise 'unknown'
        """
        explicit_cap = extract_runtime_tool_capability(raw_model)
        if explicit_cap is not None:
            return explicit_cap

        if cache_key in self._probed_cache and self._probed_cache[cache_key] != "unknown":
            return self._probed_cache[cache_key]

        return "unknown"

    async def discover_ollama(
        self,
        base_url: Optional[str] = None,
        timeout: float = 1.0,
    ) -> ProviderEntry:
        """Probe the configured Ollama runtime without buffering an unbounded catalog."""
        target_v1 = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        native_base = target_v1[:-3] if target_v1.endswith("/v1") else target_v1
        models: List[ModelEntry] = []
        is_available = False

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                status_code, data = await _request_bounded_json(
                    client,
                    "GET",
                    f"{native_base}/api/tags",
                    max_bytes=MAX_PROVIDER_JSON_RESPONSE_BYTES,
                )
                if status_code != 200:
                    status_code, data = await _request_bounded_json(
                        client,
                        "GET",
                        f"{target_v1}/models",
                        max_bytes=MAX_PROVIDER_JSON_RESPONSE_BYTES,
                    )

                if status_code == 200 and isinstance(data, dict):
                    is_available = True
                    raw_models = data.get("models", []) if "models" in data else data.get("data", [])
                    if isinstance(raw_models, list):
                        for raw_model in raw_models[:MAX_DISCOVERED_MODELS]:
                            if not isinstance(raw_model, dict):
                                continue
                            model_id = raw_model.get("name") or raw_model.get("model") or raw_model.get("id")
                            if not isinstance(model_id, str) or not model_id or len(model_id) > MAX_MODEL_ID_CHARS:
                                continue
                            cache_key = f"ollama:{model_id}"
                            models.append(
                                ModelEntry(
                                    id=model_id,
                                    label=model_id,
                                    capabilities=extract_runtime_capabilities(raw_model),
                                    tool_support=self._resolve_tool_support(cache_key, raw_model),
                                )
                            )
        except (httpx.RequestError, httpx.HTTPError, OSError) as exc:
            logger.debug(
                "Ollama local discovery probe failed (expected if not running; error type: %s).",
                type(exc).__name__,
            )

        return ProviderEntry(
            id="ollama",
            label="Ollama",
            kind="local",
            available=is_available,
            base_url=target_v1,
            models=models,
            privacy_status="local",
        )

    async def discover_lmstudio(
        self,
        base_url: Optional[str] = None,
        timeout: float = 1.0,
    ) -> ProviderEntry:
        """Probe configured LM Studio without buffering an unbounded catalog."""
        target_v1 = (base_url or settings.LMSTUDIO_BASE_URL).rstrip("/")
        models: List[ModelEntry] = []
        is_available = False

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                status_code, data = await _request_bounded_json(
                    client,
                    "GET",
                    f"{target_v1}/models",
                    max_bytes=MAX_PROVIDER_JSON_RESPONSE_BYTES,
                )
                if status_code == 200 and isinstance(data, dict):
                    is_available = True
                    raw_models = data.get("data", [])
                    if isinstance(raw_models, list):
                        for raw_model in raw_models[:MAX_DISCOVERED_MODELS]:
                            if not isinstance(raw_model, dict):
                                continue
                            model_id = raw_model.get("id")
                            if not isinstance(model_id, str) or not model_id or len(model_id) > MAX_MODEL_ID_CHARS:
                                continue
                            cache_key = f"lmstudio:{model_id}"
                            models.append(
                                ModelEntry(
                                    id=model_id,
                                    label=model_id,
                                    capabilities=extract_runtime_capabilities(raw_model),
                                    tool_support=self._resolve_tool_support(cache_key, raw_model),
                                )
                            )
        except (httpx.RequestError, httpx.HTTPError, OSError) as exc:
            logger.debug(
                "LM Studio local discovery probe failed (expected if not running; error type: %s).",
                type(exc).__name__,
            )

        return ProviderEntry(
            id="lmstudio",
            label="LM Studio",
            kind="local",
            available=is_available,
            base_url=target_v1,
            models=models,
            privacy_status="local",
        )

    def get_cloud_openai(self) -> ProviderEntry:
        """Construct normalized OpenAI provider entry based on active settings without exposing credentials."""
        api_key = settings.OPENAI_API_KEY
        is_configured = bool(api_key and api_key.strip())

        models: List[ModelEntry] = []
        if is_configured:
            default_model = settings.OPENAI_MODEL_NAME or "gpt-4o"
            known_openai = [default_model, "gpt-4o", "gpt-4o-mini", "o3-mini"]
            seen = set()
            for m in known_openai:
                if m not in seen:
                    seen.add(m)
                    models.append(
                        ModelEntry(
                            id=m,
                            label=m,
                            capabilities=["general", "code", "reasoning", "research"],
                            tool_support="supported",
                        )
                    )

        return ProviderEntry(
            id="openai",
            label="OpenAI",
            kind="cloud",
            available=is_configured,
            base_url=settings.OPENAI_BASE_URL,
            models=models,
            privacy_status="cloud",
        )

    async def discover_cloud_openai(self, timeout: float = 8.0) -> ProviderEntry:
        """Verify the configured cloud endpoint and expose only models it reports."""
        api_key = (settings.OPENAI_API_KEY or "").strip()
        base_url = (settings.OPENAI_BASE_URL or "https://api.openai.com/v1").rstrip("/")
        if not api_key:
            return ProviderEntry(
                id="openai", label="OpenAI", kind="cloud", available=False,
                base_url=base_url, models=[], privacy_status="cloud",
            )

        models: List[ModelEntry] = []
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                status_code, data = await _request_bounded_json(
                    client,
                    "GET",
                    f"{base_url}/models",
                    max_bytes=MAX_PROVIDER_JSON_RESPONSE_BYTES,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            raw_models = data.get("data", []) if status_code == 200 and isinstance(data, dict) else []
            if isinstance(raw_models, list):
                seen: set[str] = set()
                for raw_model in raw_models[:MAX_DISCOVERED_MODELS]:
                    if not isinstance(raw_model, dict):
                        continue
                    model_id = raw_model.get("id")
                    if not isinstance(model_id, str) or not model_id or len(model_id) > MAX_MODEL_ID_CHARS or model_id in seen:
                        continue
                    seen.add(model_id)
                    models.append(ModelEntry(
                        id=model_id,
                        label=model_id,
                        capabilities=["general"],
                        tool_support="unknown",
                    ))
        except (httpx.RequestError, httpx.HTTPError, OSError, ValueError) as exc:
            logger.info("Configured cloud model discovery failed (%s).", type(exc).__name__)

        return ProviderEntry(
            id="openai",
            label="OpenAI" if base_url.startswith("https://api.openai.com/") else "Connected provider",
            kind="cloud",
            available=bool(models),
            base_url=base_url,
            models=models,
            privacy_status="cloud",
        )

    def get_mock_provider(self) -> Optional[ProviderEntry]:
        """Expose mock provider when in mock testing mode."""
        if settings.MODEL_PROVIDER == "mock":
            return ProviderEntry(
                id="mock",
                label="Mock Provider",
                kind="local",
                available=True,
                base_url="mock://localhost",
                models=[
                    ModelEntry(
                        id="mock-default",
                        label="mock-default",
                        capabilities=["general", "code", "reasoning", "research"],
                        tool_support="supported",
                    ),
                    ModelEntry(
                        id="mock-fast",
                        label="mock-fast",
                        capabilities=["general", "fast"],
                        tool_support="supported",
                    ),
                    ModelEntry(
                        id="mock-pro",
                        label="mock-pro",
                        capabilities=["general", "reasoning", "research"],
                        tool_support="supported",
                    ),
                ],
                privacy_status="local",
            )
        return None

    async def discover_all(
        self,
        ollama_url: Optional[str] = None,
        lmstudio_url: Optional[str] = None,
    ) -> ModelCatalogResponse:
        """Run all provider discovery in parallel and return catalog without sensitive keys."""
        import asyncio

        ollama_task = self.discover_ollama(ollama_url or settings.OLLAMA_BASE_URL)
        lmstudio_task = self.discover_lmstudio(lmstudio_url or settings.LMSTUDIO_BASE_URL)
        openai_task = self.discover_cloud_openai()

        ollama_entry, lmstudio_entry, openai_entry = await asyncio.gather(ollama_task, lmstudio_task, openai_task)

        providers = [ollama_entry, lmstudio_entry, openai_entry]
        mock_entry = self.get_mock_provider()
        if mock_entry:
            providers.append(mock_entry)

        return ModelCatalogResponse(providers=providers)

    async def register_discovered_providers(
        self,
        router: Optional[ModelRouter] = None,
        catalog: Optional[ModelCatalogResponse] = None,
        ollama_url: Optional[str] = None,
        lmstudio_url: Optional[str] = None,
    ) -> ModelCatalogResponse:
        """
        Register any discovered available local providers with the ModelRouter.
        Accepts an optional pre-computed catalog snapshot to avoid redundant discovery requests.
        """
        target_router = router or model_router
        if catalog is None:
            catalog = await self.discover_all(ollama_url, lmstudio_url)

        for p in catalog.providers:
            if p.id == "ollama" and p.available and p.models:
                prov = OpenAICompatibleProvider(
                    provider_name="ollama",
                    base_url=p.base_url,
                    api_key="ollama",
                    model_name=p.models[0].id,
                )
                tool_support_map = {m.id: m.tool_support for m in p.models}
                target_router.register_provider(
                    prov,
                    ProviderMetadata(
                        name="ollama",
                        capabilities=["general", "code", "local"],
                        privacy_status="local",
                        cost_class="low",
                        latency_class="low",
                        default_model=p.models[0].id,
                        models=[m.id for m in p.models],
                        allow_arbitrary_models=True,
                        tool_support=tool_support_map,
                        model_context_windows={m.id: m.context_window for m in p.models if m.context_window is not None},
                    ),
                )
                logger.info(f"Registered local Ollama provider with {len(p.models)} models")

            elif p.id == "lmstudio" and p.available and p.models:
                prov = OpenAICompatibleProvider(
                    provider_name="lmstudio",
                    base_url=p.base_url,
                    api_key="lmstudio",
                    model_name=p.models[0].id,
                )
                tool_support_map = {m.id: m.tool_support for m in p.models}
                target_router.register_provider(
                    prov,
                    ProviderMetadata(
                        name="lmstudio",
                        capabilities=["general", "code", "local"],
                        privacy_status="local",
                        cost_class="low",
                        latency_class="low",
                        default_model=p.models[0].id,
                        models=[m.id for m in p.models],
                        allow_arbitrary_models=True,
                        tool_support=tool_support_map,
                        model_context_windows={m.id: m.context_window for m in p.models if m.context_window is not None},
                    ),
                )
                logger.info(f"Registered local LM Studio provider with {len(p.models)} models")

        return catalog

    async def probe_model_capability(
        self,
        provider_id: str,
        model_id: str,
        base_url: Optional[str] = None,
    ) -> CapabilityProbeResult:
        """
        Explicitly test a model's ability to emit structured tool calls.
        Local provider responses are byte-bounded; non-observation remains
        unknown because a model may choose not to call a tool.
        """
        if provider_id not in {"ollama", "lmstudio"}:
            return CapabilityProbeResult(
                provider_id=provider_id,
                model_id=model_id,
                tool_support="supported",
                details="Cloud / Mock providers support tool calling by default.",
            )

        target_url = (
            base_url
            or (settings.OLLAMA_BASE_URL if provider_id == "ollama" else settings.LMSTUDIO_BASE_URL)
        ).rstrip("/")
        cache_key = f"{provider_id}:{model_id}"
        probe_payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": "Please invoke probe_test function with status 'ok'.",
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "probe_test",
                        "description": "Probe test function",
                        "parameters": {
                            "type": "object",
                            "properties": {"status": {"type": "string"}},
                            "required": ["status"],
                        },
                    },
                }
            ],
            "tool_choice": "auto",
            "temperature": 0.0,
            "max_tokens": 128,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                status_code, data = await _request_bounded_json(
                    client,
                    "POST",
                    f"{target_url}/chat/completions",
                    max_bytes=MAX_CAPABILITY_PROBE_RESPONSE_BYTES,
                    json=probe_payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {provider_id}",
                    },
                )
                if status_code == 200 and not isinstance(data, dict):
                    self._probed_cache[cache_key] = "unknown"
                    return CapabilityProbeResult(
                        provider_id=provider_id,
                        model_id=model_id,
                        tool_support="unknown",
                        details="Provider returned an invalid or oversized probe response; tool support remains unknown.",
                    )

                if status_code == 200:
                    choices = data.get("choices", [])
                    message = (
                        choices[0].get("message", {})
                        if isinstance(choices, list) and choices and isinstance(choices[0], dict)
                        else {}
                    )
                    if isinstance(message, dict) and message.get("tool_calls"):
                        self._probed_cache[cache_key] = "supported"
                        return CapabilityProbeResult(
                            provider_id=provider_id,
                            model_id=model_id,
                            tool_support="supported",
                            details="Model successfully emitted structured tool call.",
                        )
                    self._probed_cache[cache_key] = "unknown"
                    return CapabilityProbeResult(
                        provider_id=provider_id,
                        model_id=model_id,
                        tool_support="unknown",
                        details="Model responded without a tool call; tool support remains unknown.",
                    )

                if status_code == 400:
                    self._probed_cache[cache_key] = "unknown"
                    return CapabilityProbeResult(
                        provider_id=provider_id,
                        model_id=model_id,
                        tool_support="unknown",
                        details=(
                            "Provider rejected the capability probe request (HTTP 400); "
                            "tool support remains unknown."
                        ),
                    )

                self._probed_cache[cache_key] = "unknown"
                return CapabilityProbeResult(
                    provider_id=provider_id,
                    model_id=model_id,
                    tool_support="unknown",
                    details=f"Provider returned HTTP {status_code}. Status unknown or provider unavailable.",
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RequestError, OSError):
            self._probed_cache[cache_key] = "unknown"
            return CapabilityProbeResult(
                provider_id=provider_id,
                model_id=model_id,
                tool_support="unknown",
                details="Connection probe failed or timed out. Provider unavailable; tool support remains unknown.",
            )
        except Exception:
            self._probed_cache[cache_key] = "unknown"
            return CapabilityProbeResult(
                provider_id=provider_id,
                model_id=model_id,
                tool_support="unknown",
                details="Capability probe failed unexpectedly; tool support remains unknown.",
            )


# Singleton discovery service
model_discovery_service = ModelDiscoveryService()
