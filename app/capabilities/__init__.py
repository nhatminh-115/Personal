"""Typed capability-provider contracts used by the Kuractus control plane."""

from app.capabilities.registry import (
    CapabilityProvider,
    CapabilityProviderHealth,
    CapabilityProviderMetadata,
    CapabilityProviderRegistration,
    CapabilityProviderRegistry,
    NetworkRequirement,
    PrivacyBoundary,
    ProviderApprovalRequirement,
    ProviderPermission,
)

__all__ = [
    "CapabilityProvider",
    "CapabilityProviderHealth",
    "CapabilityProviderMetadata",
    "CapabilityProviderRegistration",
    "CapabilityProviderRegistry",
    "NetworkRequirement",
    "PrivacyBoundary",
    "ProviderApprovalRequirement",
    "ProviderPermission",
]
