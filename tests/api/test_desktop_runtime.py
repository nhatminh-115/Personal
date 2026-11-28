from fastapi.testclient import TestClient

from app.api.server import create_app
from app.core.settings import settings


def test_desktop_shutdown_route_is_registered_only_in_desktop_mode(monkeypatch):
    monkeypatch.setattr(settings, "DESKTOP_MODE", False)
    monkeypatch.setattr(settings, "AURA_API_TOKEN", None)
    browser_client = TestClient(create_app())
    assert browser_client.post("/v1/internal/desktop/shutdown").status_code == 404

    monkeypatch.setattr(settings, "DESKTOP_MODE", True)
    desktop_app = create_app()
    desktop_client = TestClient(desktop_app)
    response = desktop_client.post("/v1/internal/desktop/shutdown")

    assert response.status_code == 202
    assert response.json() == {"status": "shutting_down"}
    assert desktop_app.state.desktop_shutdown_event.is_set()
