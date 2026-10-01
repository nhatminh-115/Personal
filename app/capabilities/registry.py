"""Typed inventory and capability-to-tool bindings for runtime providers.

Provider metadata is descriptive. Existing AURA tool permission and approval
checks remain authoritative for every invocation.
"""

from enum import Enum
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class CapabilityProviderHealth(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class PrivacyBoundary(str, Enum):
    UNKNOWN = "unknown"
    LOCAL = "local"
    CLOUD = "cloud"
    MIXED = "mixed"


class NetworkRequirement(str, Enum):
    UNKNOWN = "unknown"
    NONE = "none"
    LOCAL = "local"
    INTERNET = "internet"


class ProviderPermission(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


class ProviderApprovalRequirement(str, Enum):
    UNKNOWN = "unknown"
    PER_TOOL_POLICY = "per_tool_policy"
    ALWAYS = "always"


class CapabilityProviderMetadata(BaseModel):
    """Sanitized provider facts surfaced by the AURA control plane."""

    model_config = ConfigDict(frozen=True)

    provider_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]*$")
    name: str = Field(min_length=1, max_length=160)
    version: Optional[str] = Field(default=None, max_length=80)
    health: CapabilityProviderHealth = CapabilityProviderHealth.UNKNOWN
    health_checked_at: Optional[datetime] = None
    enabled: bool = True
    capabilities: List[str] = Field(default_factory=list)
    privacy_boundary: PrivacyBoundary = PrivacyBoundary.UNKNOWN
    network_requirement: NetworkRequirement = NetworkRequirement.UNKNOWN
    data_touched: Optional[List[str]] = None
    permissions: Optional[List[ProviderPermission]] = None
    approval_requirement: ProviderApprovalRequirement = ProviderApprovalRequirement.UNKNOWN


class CapabilityProviderRegistration(BaseModel):
    """Serializable registration contract shared by native and external providers."""

    metadata: CapabilityProviderMetadata
    capability_tools: Dict[str, List[str]] = Field(default_factory=dict)


@runtime_checkable
class CapabilityProvider(Protocol):
    """Provider boundary: describe capabilities and bind them to canonical AURA tools."""

    @property
    def metadata(self) -> CapabilityProviderMetadata: ...

    @property
    def capability_tools(self) -> Mapping[str, Sequence[str]]: ...


class CapabilityProviderRegistry:
    """Stores provider metadata and explicit abstract-capability bindings."""

    def __init__(self) -> None:
        self._metadata: Dict[str, CapabilityProviderMetadata] = {}
        self._capability_tools: Dict[str, Dict[str, List[str]]] = {}

    def register(
        self,
        metadata: CapabilityProviderMetadata,
        capability_tools: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        bindings = {capability: list(dict.fromkeys(names)) for capability, names in (capability_tools or {}).items()}
        undeclared = set(bindings) - set(metadata.capabilities)
        if undeclared:
            raise ValueError(f"Provider '{metadata.provider_id}' binds undeclared capabilities: {sorted(undeclared)}")
        if any(not names for names in bindings.values()):
            raise ValueError("Capability bindings must reference at least one canonical AURA tool.")
        self._metadata[metadata.provider_id] = metadata
        self._capability_tools[metadata.provider_id] = bindings

    def register_provider(self, provider: CapabilityProvider) -> None:
        """Register any structural provider implementation through the typed boundary."""
        self.register(
            provider.metadata,
            {capability: list(tool_names) for capability, tool_names in provider.capability_tools.items()},
        )

    def unregister(self, provider_id: str) -> None:
        self._metadata.pop(provider_id, None)
        self._capability_tools.pop(provider_id, None)

    def get(self, provider_id: str) -> Optional[CapabilityProviderMetadata]:
        return self._metadata.get(provider_id)

    def list_providers(self) -> List[CapabilityProviderMetadata]:
        return sorted(self._metadata.values(), key=lambda item: item.provider_id)

    def resolve_tools(
        self,
        capabilities: Iterable[str],
        allowed_tool_names: Optional[Iterable[str]] = None,
    ) -> List[str]:
        requested = list(dict.fromkeys(capabilities))
        allowed = set(allowed_tool_names) if allowed_tool_names is not None else None
        resolved: List[str] = []
        missing: List[str] = []
        for capability in requested:
            matches: List[List[str]] = []
            for provider_id, bindings in self._capability_tools.items():
                metadata = self._metadata[provider_id]
                if not metadata.enabled or metadata.health not in {
                    CapabilityProviderHealth.HEALTHY,
                    CapabilityProviderHealth.DEGRADED,
                    CapabilityProviderHealth.UNKNOWN,
                }:
                    continue
                names = bindings.get(capability, [])
                if allowed is not None:
                    names = [name for name in names if name in allowed]
                if names:
                    matches.append(names)
            if not matches:
                missing.append(capability)
                continue
            for names in matches:
                resolved.extend(names)
        if missing:
            raise UnresolvedCapabilitiesError(missing)
        return list(dict.fromkeys(resolved))


class UnresolvedCapabilitiesError(ValueError):
    def __init__(self, capabilities: List[str]) -> None:
        self.capabilities = capabilities
        super().__init__(f"No enabled provider currently implements: {', '.join(capabilities)}")
