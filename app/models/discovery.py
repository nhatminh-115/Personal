"""Dynamic model and local provider discovery service for AURA."""

import json
from typing import Any, Dict, List, Literal, Optional
import httpx
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.core.settings import settings
from app.models.openai_provider import OpenAICompatibleProvider
from app.models.router import ModelRouter, model_router
from app.models.routing_policy import ProviderMetadata


class ModelEntry(BaseModel):
    """Normalized descriptor of an individual model."""

    id: str
    label: str
    capabilities: List[str] = Field(default_factory=list)
    tool_support: Literal["supported", "unsupported", "unknown"] = "unknown"
    context_window: Optional[int] = None


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


def extract_runtime_tool_capability(raw_model: Dict[str, Any]) -> Optional[Literal["supported", "unsupported"]]:
    """Extract explicit tool capability metadata reported by local runtime, when available."""
    # 1. Direct capabilities list or dict
    caps = raw_model.get("capabilities")
    if isinstance(caps, list):
        caps_lower = [str(c).lower() for c in caps]
        if any(c in caps_lower for c in ("tools", "tool_calls", "function_calling", "functions")):
            return "supported"
    elif isinstance(caps, dict):
        if any(caps.get(k) is True for k in ("tools", "tool_calls", "function_calling", "functions")):
            return "supported"
        if any(caps.get(k) is False for k in ("tools", "tool_calls", "function_calling", "functions")):
            return "unsupported"

    # 2. Direct boolean fields on raw_model
    if raw_model.get("tools") is True or raw_model.get("tool_calls") is True:
        return "supported"
    if raw_model.get("tools") is False or raw_model.get("tool_calls") is False:
        return "unsupported"

    # 3. Nested in details dictionary
    details = raw_model.get("details")
    if isinstance(details, dict):
        det_caps = details.get("capabilities")
        if isinstance(det_caps, list):
            caps_lower = [str(c).lower() for c in det_caps]
            if any(c in caps_lower for c in ("tools", "tool_calls", "function_calling", "functions")):
                return "supported"
        elif isinstance(det_caps, dict):
            if any(det_caps.get(k) is True for k in ("tools", "tool_calls", "function_calling", "functions")):
                return "supported"
            if any(det_caps.get(k) is False for k in ("tools", "tool_calls", "function_calling", "functions")):
                return "unsupported"

    return None


def infer_tool_support(model_id: str) -> Literal["supported", "unsupported", "unknown"]:
    """Conservative fallback: returns unknown without model-name regex heuristics."""
    return "unknown"


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
        """Probe local Ollama runtime safely."""
        target_v1 = (base_url or "http://127.0.0.1:11434/v1").rstrip("/")
        # Derive native base url for /api/tags
        native_base = target_v1[:-3] if target_v1.endswith("/v1") else target_v1
        models: List[ModelEntry] = []
        is_available = False

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 1. Try native tags endpoint
                resp = await client.get(f"{native_base}/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    is_available = True
                    for m in data.get("models", []):
                        m_name = m.get("name") or m.get("model", "")
                        if m_name:
                            cache_key = f"ollama:{m_name}"
                            tool_sup = self._resolve_tool_support(cache_key, m)
                            models.append(
                                ModelEntry(
                                    id=m_name,
                                    label=m_name,
                                    capabilities=["general", "code", "local"],
                                    tool_support=tool_sup,
                                )
                            )
                else:
                    # Fallback to /v1/models
                    resp_v1 = await client.get(f"{target_v1}/models")
                    if resp_v1.status_code == 200:
                        is_available = True
                        data_v1 = resp_v1.json()
                        for m in data_v1.get("data", []):
                            m_id = m.get("id", "")
                            if m_id:
                                cache_key = f"ollama:{m_id}"
                                tool_sup = self._resolve_tool_support(cache_key, m)
                                models.append(
                                    ModelEntry(
                                        id=m_id,
                                        label=m_id,
                                        capabilities=["general", "code", "local"],
                                        tool_support=tool_sup,
                                    )
                                )
        except (httpx.RequestError, httpx.HTTPError, OSError) as e:
            logger.debug(f"Ollama local discovery probe failed (expected if not running): {e}")
            is_available = False

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
        """Probe local LM Studio runtime safely."""
        target_v1 = (base_url or "http://127.0.0.1:1234/v1").rstrip("/")
        models: List[ModelEntry] = []
        is_available = False

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{target_v1}/models")
                if resp.status_code == 200:
                    is_available = True
                    data = resp.json()
                    for m in data.get("data", []):
                        m_id = m.get("id", "")
                        if m_id:
                            cache_key = f"lmstudio:{m_id}"
                            tool_sup = self._resolve_tool_support(cache_key, m)
                            models.append(
                                ModelEntry(
                                    id=m_id,
                                    label=m_id,
                                    capabilities=["general", "code", "local"],
                                    tool_support=tool_sup,
                                )
                            )
        except (httpx.RequestError, httpx.HTTPError, OSError) as e:
            logger.debug(f"LM Studio local discovery probe failed (expected if not running): {e}")
            is_available = False

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

        ollama_task = self.discover_ollama(ollama_url)
        lmstudio_task = self.discover_lmstudio(lmstudio_url)

        ollama_entry, lmstudio_entry = await asyncio.gather(ollama_task, lmstudio_task)
        openai_entry = self.get_cloud_openai()

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
        Only marks 'unsupported' when the runtime/model successfully responds
        and provides meaningful evidence that structured tool calling is unsupported.
        Connection errors or timeouts yield 'unknown' / provider unavailable.
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
            or ("http://127.0.0.1:11434/v1" if provider_id == "ollama" else "http://127.0.0.1:1234/v1")
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
                resp = await client.post(
                    f"{target_url}/chat/completions",
                    json=probe_payload,
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {provider_id}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        msg = choices[0].get("message", {})
                        if msg.get("tool_calls"):
                            self._probed_cache[cache_key] = "supported"
                            return CapabilityProbeResult(
                                provider_id=provider_id,
                                model_id=model_id,
                                tool_support="supported",
                                details="Model successfully emitted structured tool call.",
                            )
                    # Model responded successfully (200), but emitted no tool calls despite tool request
                    self._probed_cache[cache_key] = "unsupported"
                    return CapabilityProbeResult(
                        provider_id=provider_id,
                        model_id=model_id,
                        tool_support="unsupported",
                        details="Model responded without tool calls when function calling was requested.",
                    )
                elif resp.status_code == 400:
                    err_msg = ""
                    try:
                        err_msg = resp.json().get("error", {}).get("message", "")
                    except Exception:
                        err_msg = resp.text
                    self._probed_cache[cache_key] = "unsupported"
                    return CapabilityProbeResult(
                        provider_id=provider_id,
                        model_id=model_id,
                        tool_support="unsupported",
                        details=f"Runtime rejected tool calling schema (HTTP 400): {err_msg}",
                    )
                else:
                    # 5xx or other status: provider unavailable or error, NOT unsupported
                    self._probed_cache[cache_key] = "unknown"
                    return CapabilityProbeResult(
                        provider_id=provider_id,
                        model_id=model_id,
                        tool_support="unknown",
                        details=f"Provider returned HTTP {resp.status_code}. Status unknown or provider unavailable.",
                    )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RequestError, OSError) as e:
            # Failed connection/timeout: unknown or provider unavailable, NOT unsupported!
            self._probed_cache[cache_key] = "unknown"
            return CapabilityProbeResult(
                provider_id=provider_id,
                model_id=model_id,
                tool_support="unknown",
                details=f"Connection probe failed or timed out: {e}. Provider unavailable.",
            )
        except Exception as e:
            self._probed_cache[cache_key] = "unknown"
            return CapabilityProbeResult(
                provider_id=provider_id,
                model_id=model_id,
                tool_support="unknown",
                details=f"Unexpected probe failure: {e}",
            )


# Singleton discovery service
model_discovery_service = ModelDiscoveryService()
