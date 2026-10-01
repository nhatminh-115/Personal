"""AURA control-plane inventory for abstract runtime capabilities."""

from fastapi import APIRouter

from app.api.schemas import CapabilityProvidersResponse
from app.tools.registry import tool_registry

router = APIRouter(prefix="/v1/capabilities", tags=["Capabilities"])


@router.get("/providers", response_model=CapabilityProvidersResponse)
async def list_capability_providers() -> CapabilityProvidersResponse:
    """Return sanitized provider metadata; credentials, endpoint URLs, and tool inputs are excluded."""
    return CapabilityProvidersResponse(
        providers=tool_registry.capability_providers.list_providers()
    )
