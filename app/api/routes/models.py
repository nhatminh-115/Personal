"""Model registry and dynamic discovery routes: /v1/models."""

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_model_router
from app.api.schemas import (
    ModelCatalogResponse,
    ModelInfoResponse,
    ModelProbeRequest,
    ModelProbeResponse,
    ProviderInfoResponse,
)
from app.models.discovery import model_discovery_service
from app.models.router import ModelRouter

router = APIRouter(prefix="/v1/models", tags=["Models"])


def _build_catalog_response(catalog: ModelCatalogResponse) -> ModelCatalogResponse:
    return ModelCatalogResponse(
        providers=[
            ProviderInfoResponse(
                id=p.id,
                label=p.label,
                kind=p.kind,
                available=p.available,
                base_url=p.base_url,
                models=[
                    ModelInfoResponse(
                        id=m.id,
                        label=m.label,
                        capabilities=m.capabilities,
                        tool_support=m.tool_support,
                    )
                    for m in p.models
                ],
                privacy_status=p.privacy_status,
            )
            for p in catalog.providers
        ]
    )


@router.get("", response_model=ModelCatalogResponse, status_code=status.HTTP_200_OK)
async def get_models(
    router_instance: ModelRouter = Depends(get_model_router),
) -> ModelCatalogResponse:
    """
    List available local and cloud model providers and their discovered models.
    Strictly sanitizes internal credentials: never exposes API keys or headers.
    Uses a single discovery snapshot to populate the response and register providers.
    """
    catalog = await model_discovery_service.discover_all()
    await model_discovery_service.register_discovered_providers(router_instance, catalog=catalog)
    return _build_catalog_response(catalog)


@router.post("/probe", response_model=ModelProbeResponse, status_code=status.HTTP_200_OK)
async def probe_model(req: ModelProbeRequest) -> ModelProbeResponse:
    """Explicit user-triggered test of a model's structured tool calling ability."""
    res = await model_discovery_service.probe_model_capability(
        provider_id=req.provider_id,
        model_id=req.model_id,
    )
    return ModelProbeResponse(
        provider_id=res.provider_id,
        model_id=res.model_id,
        tool_support=res.tool_support,
        details=res.details,
    )


@router.post("/refresh", response_model=ModelCatalogResponse, status_code=status.HTTP_200_OK)
async def refresh_models(
    router_instance: ModelRouter = Depends(get_model_router),
) -> ModelCatalogResponse:
    """
    Manually re-trigger provider detection and register newly available providers.
    Executes a single discovery snapshot without redundant probes.
    """
    catalog = await model_discovery_service.discover_all()
    await model_discovery_service.register_discovered_providers(router_instance, catalog=catalog)
    return _build_catalog_response(catalog)
