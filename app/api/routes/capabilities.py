"""AURA control-plane inventory for abstract runtime capabilities."""

from fastapi import APIRouter

from app.api.schemas import CapabilityProviderResponse, CapabilityProvidersResponse
from app.tools.registry import tool_registry

router = APIRouter(prefix="/v1/capabilities", tags=["Capabilities"])


@router.get("/providers", response_model=CapabilityProvidersResponse)
async def list_capability_providers() -> CapabilityProvidersResponse:
    """Return sanitized provider metadata; credentials, endpoint URLs, and tool inputs are excluded."""
    registry = tool_registry.capability_providers
    providers = [
        CapabilityProviderResponse(
            **metadata.model_dump(),
            capability_tools=registry.get_capability_tools(metadata.provider_id),
        )
        for metadata in registry.list_providers()
    ]
    return CapabilityProvidersResponse(providers=providers)
