"""The packaged web UI loads without weakening shared-token API protection."""

import httpx
import pytest
from pydantic import SecretStr

from app.api import server
from app.core.settings import settings


@pytest.mark.asyncio
async def test_packaged_web_assets_are_public_but_api_and_docs_remain_protected(tmp_path, monkeypatch):
    files = {
        "index.html": '<html><div id="root"></div></html>',
        "assets/app.js": "window.auraLoaded = true;",
        "ocr/worker.js": "self.auraWorker = true;",
        "mock-files/example.pdf": "sample pdf",
        "robots.txt": "private static file",
    }
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    monkeypatch.setattr(server, "WEB_DIST_DIR", tmp_path)
    monkeypatch.setattr(settings, "AURA_API_TOKEN", SecretStr("aura-static-test-token-0123456789abcdef"))
    app = server.create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://aura.test") as client:
        for path in ("/", "/index.html", "/assets/app.js", "/ocr/worker.js", "/mock-files/example.pdf"):
            response = await client.get(path)
            assert response.status_code == 200, path

        assert "auraLoaded" in (await client.get("/assets/app.js")).text
        assert (await client.get("/robots.txt")).status_code == 401
        assert (await client.get("/docs")).status_code == 401
        assert (await client.get("/openapi.json")).status_code == 401
        assert (await client.get("/v1/not-found")).status_code == 401

        authorized_not_found = await client.get(
            "/v1/not-found",
            headers={"Authorization": "Bearer aura-static-test-token-0123456789abcdef"},
        )
        assert authorized_not_found.status_code == 404
        assert authorized_not_found.json() == {"detail": "Not Found"}


@pytest.mark.asyncio
async def test_web_shell_is_not_public_when_no_production_build_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WEB_DIST_DIR", tmp_path)
    monkeypatch.setattr(settings, "AURA_API_TOKEN", SecretStr("aura-static-test-token-0123456789abcdef"))
    app = server.create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://aura.test") as client:
        response = await client.get("/")

    assert response.status_code == 401
