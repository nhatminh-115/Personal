"""Privacy checks for local model endpoint metadata and discovery logs."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.discovery import ModelDiscoveryService, public_provider_base_url


def test_public_provider_base_url_redacts_userinfo_query_secrets_and_fragment():
    configured_url = (
        "https://aura-user:private-password@model-host.internal/v1"
        "?api_key=query-secret&region=us&access_token=access-secret"
        "&X-Amz-Signature=sig-secret&monkey=value#private-fragment"
    )

    safe_url = public_provider_base_url(configured_url)

    assert safe_url == (
        "https://model-host.internal/v1"
        "?api_key=%5BREDACTED%5D&region=us&access_token=%5BREDACTED%5D"
        "&X-Amz-Signature=%5BREDACTED%5D&monkey=value"
    )
    for secret in ("aura-user", "private-password", "query-secret", "access-secret", "sig-secret", "private-fragment"):
        assert secret not in safe_url


@pytest.mark.parametrize("provider_method", ["discover_ollama", "discover_lmstudio"])
@pytest.mark.asyncio
async def test_local_discovery_logs_only_safe_exception_type(monkeypatch, provider_method):
    configured_url = "http://local-user:local-password@model-host.internal/v1?api_key=local-token"
    diagnostic = f"request failed for {configured_url}: private response body"
    logger = MagicMock()
    monkeypatch.setattr("app.models.discovery.logger", logger)
    service = ModelDiscoveryService()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=httpx.ConnectError(diagnostic)):
        provider = await getattr(service, provider_method)(base_url=configured_url)

    assert provider.available is False
    assert provider.base_url == configured_url
    logger.debug.assert_called_once()
    log_call = repr(logger.debug.call_args)
    assert "ConnectError" in log_call
    assert diagnostic not in log_call
    assert "local-password" not in log_call
    assert "local-token" not in log_call
