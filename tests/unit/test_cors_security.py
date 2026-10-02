"""The local personal API must not grant browser access to arbitrary sites."""

import httpx
import pytest

from app.api.server import create_app
from app.core.settings import settings


@pytest.mark.asyncio
async def test_cors_allows_configured_local_frontend_origin(monkeypatch):
    monkeypatch.setattr(
        settings,
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173, http://127.0.0.1:5173",
    )
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://aura.test") as client:
        response = await client.options(
            "/v1/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.asyncio
async def test_cors_rejects_unconfigured_site_origin(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://aura.test") as client:
        response = await client.get(
            "/openapi.json",
            headers={"Origin": "https://untrusted.example"},
        )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
