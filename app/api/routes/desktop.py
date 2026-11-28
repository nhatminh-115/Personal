"""Desktop-only local runtime control endpoints."""

from fastapi import APIRouter, HTTPException, Request, status

from app.core.settings import settings

router = APIRouter(prefix="/v1/internal/desktop", tags=["Desktop runtime"])


@router.post("/shutdown", status_code=status.HTTP_202_ACCEPTED)
async def request_desktop_shutdown(request: Request) -> dict[str, str]:
    """Request a graceful sidecar exit; only registered in desktop mode."""
    if not settings.DESKTOP_MODE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    shutdown_event = getattr(request.app.state, "desktop_shutdown_event", None)
    if shutdown_event is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Desktop shutdown is unavailable.")
    shutdown_event.set()
    return {"status": "shutting_down"}
