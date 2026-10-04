"""AURA control-plane inventory for abstract runtime capabilities."""

from fastapi import APIRouter, HTTPException, status

from app.api.schemas import CapabilityProviderResponse, CapabilityProvidersResponse
from app.mcp.manager import mcp_manager
from app.tools.registry import tool_registry

router = APIRouter(prefix="/v1/capabilities", tags=["Capabilities"])


def _provider_response(provider_id: str) -> CapabilityProviderResponse | None:
    registry = tool_registry.capability_providers
    metadata = registry.get(provider_id)
    if metadata is None:
        return None
    return CapabilityProviderResponse(
        **metadata.model_dump(),
        capability_tools=registry.get_capability_tools(provider_id),
        declared_capability_tools=registry.get_declared_capability_tools(provider_id),
    )


@router.get("/providers", response_model=CapabilityProvidersResponse)
async def list_capability_providers() -> CapabilityProvidersResponse:
    """Return sanitized provider metadata; credentials, endpoint URLs, and tool inputs are excluded."""
    registry = tool_registry.capability_providers
    providers = [
        provider
        for metadata in registry.list_providers()
        if (provider := _provider_response(metadata.provider_id)) is not None
    ]
    return CapabilityProvidersResponse(providers=providers)


@router.post("/providers/{provider_id}/refresh", response_model=CapabilityProviderResponse)
async def refresh_mcp_provider(provider_id: str) -> CapabilityProviderResponse:
    """Re-run tools/list for one configured MCP provider without invoking its tools."""
    if not provider_id.startswith("mcp."):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP provider was not found.")

    server_id = provider_id.removeprefix("mcp.")
    if mcp_manager.get_server_config(server_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP provider was not found.")

    await mcp_manager.discover_tools(server_id)
    response = _provider_response(provider_id)
    if response is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MCP provider was not found.")
    return response
