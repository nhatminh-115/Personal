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


KNOWN_TOOL_CALLING_FAMILIES = {
    "llama3.1",
    "llama3.2",
    "llama-3.1",
    "llama-3.2",
    "mistral",
    "mixtral",
    "qwen2.5",
    "qwen-2.5",
    "command-r",
    "hermes",
    "functionary",
    "gpt-4",
    "gpt-3.5",
}


def infer_tool_support(model_id: str) -> Literal["supported", "unsupported", "unknown"]:
    """Heuristic tool capability inference based on model identifier family."""
    mid = model_id.lower()
    for fam in KNOWN_TOOL_CALLING_FAMILIES:
        if fam in mid:
            return "supported"
    return "unknown"


class ModelDiscoveryService:
    """Discovers and registers local (Ollama, LM Studio) and cloud model providers."""

    def __init__(self) -> None:
        self._probed_cache: Dict[str, Literal["supported", "unsupported", "unknown"]] = {}

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
                            tool_sup = self._probed_cache.get(cache_key) or infer_tool_support(m_name)
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
                                tool_sup = self._probed_cache.get(cache_key) or infer_tool_support(m_id)
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
                            tool_sup = self._probed_cache.get(cache_key) or infer_tool_support(m_id)
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
        ollama_url: Optional[str] = None,
        lmstudio_url: Optional[str] = None,
    ) -> None:
        """Register any discovered available local providers with the ModelRouter."""
        target_router = router or model_router
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

    async def probe_model_capability(
        self,
        provider_id: str,
        model_id: str,
        base_url: Optional[str] = None,
    ) -> CapabilityProbeResult:
        """Explicitly test a model's ability to emit structured tool calls."""
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
                            self._probed_cache[f"{provider_id}:{model_id}"] = "supported"
                            return CapabilityProbeResult(
                                provider_id=provider_id,
                                model_id=model_id,
                                tool_support="supported",
                                details="Model successfully emitted structured tool call.",
                            )

                self._probed_cache[f"{provider_id}:{model_id}"] = "unsupported"
                return CapabilityProbeResult(
                    provider_id=provider_id,
                    model_id=model_id,
                    tool_support="unsupported",
                    details=f"Model responded without tool calls (status {resp.status_code}).",
                )
        except Exception as e:
            self._probed_cache[f"{provider_id}:{model_id}"] = "unsupported"
            return CapabilityProbeResult(
                provider_id=provider_id,
                model_id=model_id,
                tool_support="unsupported",
                details=f"Connection probe failed: {e}",
            )


# Singleton discovery service
model_discovery_service = ModelDiscoveryService()
