"""FastAPI server application initialization."""

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import approvals, automations, capabilities, chat, memory, models, runs, sessions, routing, routing_confirmations, study, workspace
from app.api.middleware import RequestBodyLimitMiddleware
from app.core.errors import AuraError, PermissionDeniedError, WorkspaceEscapeError
from app.core.logging import logger
from app.core.settings import settings
from app.db.session import get_db, init_db


from app.orchestrator.graph import close_checkpointer, init_checkpointer, is_checkpointer_initialized


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    # Ensure database schema is initialized
    await init_db()
    # Ensure persistent checkpointer is initialized
    await init_checkpointer()

    # Discover and register local and cloud model providers dynamically
    try:
        from app.models.discovery import model_discovery_service
        await model_discovery_service.register_discovered_providers()
    except Exception as e:
        logger.warning(f"Non-fatal error during model discovery: {e}")

    # Load and initialize MCP servers from persistent configuration
    try:
        from app.mcp.loader import load_mcp_servers_from_file
        from app.mcp.manager import mcp_manager

        if settings.MCP_CONFIG_PATH:
            configured_servers = load_mcp_servers_from_file(settings.MCP_CONFIG_PATH)
            for srv in configured_servers:
                mcp_manager.register_server(srv)

        for srv in mcp_manager.list_servers():
            if srv.enabled:
                await mcp_manager.discover_tools(srv.id)
    except Exception as e:
        logger.warning(f"Non-fatal error during startup MCP tool loading/discovery: {e}")

    from app.events.runtime import start_automation_runtime

    stop_automation_runtime = await start_automation_runtime()

    try:
        yield
    finally:
        logger.info(f"Shutting down {settings.APP_NAME}")
        await stop_automation_runtime()
        try:
            from app.mcp.manager import mcp_manager
            await mcp_manager.disconnect_all()
        except Exception as e:
            logger.warning(f"Error disconnecting MCP servers on shutdown: {e}")

        await close_checkpointer()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Production-grade personal AI agent runtime with persistent memory, capability-based tools, and human-in-the-loop approvals.",
        lifespan=lifespan,
    )

    allowed_origins = [
        origin.strip()
        for origin in settings.CORS_ALLOWED_ORIGINS.split(",")
        if origin.strip()
    ]
    app.add_middleware(RequestBodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        expose_headers=["X-Next-Cursor"],
    )

    # Register Routers
    app.include_router(chat.router)
    app.include_router(approvals.router)
    app.include_router(sessions.router)
    app.include_router(runs.router)
    app.include_router(models.router)
    app.include_router(memory.router)
    app.include_router(routing.router)
    app.include_router(routing_confirmations.router)
    app.include_router(workspace.router)
    app.include_router(study.router)
    app.include_router(automations.router)
    app.include_router(capabilities.router)

    # Global Domain Exception Handlers
    @app.exception_handler(WorkspaceEscapeError)
    async def workspace_escape_handler(request: Request, exc: WorkspaceEscapeError):
        logger.warning(f"Security Alert: Workspace escape attempted: {exc.message}")
        return JSONResponse(
            status_code=403,
            content={"error": "ACCESS_DENIED", "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(PermissionDeniedError)
    async def permission_denied_handler(request: Request, exc: PermissionDeniedError):
        logger.warning(f"Permission denied: {exc.message}")
        return JSONResponse(
            status_code=403,
            content={"error": "PERMISSION_DENIED", "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(AuraError)
    async def aura_error_handler(request: Request, exc: AuraError):
        logger.error(f"Domain error: {exc.message}")
        return JSONResponse(
            status_code=400,
            content={"error": exc.__class__.__name__, "message": exc.message, "details": exc.details},
        )

    @app.get("/health", tags=["Health"])
    async def health_check():
        """Liveness probe; dependency readiness is reported separately."""
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }

    @app.get("/ready", tags=["Health"])
    async def readiness_check(response: Response, db: AsyncSession = Depends(get_db)):
        """Report whether dependencies required for durable runs are ready."""
        try:
            await db.execute(text("SELECT 1"))
            database_status = "healthy"
        except Exception:
            database_status = "unavailable"

        checkpointer_status = "healthy" if is_checkpointer_initialized() else "unavailable"
        checks = {"database": database_status, "checkpointer": checkpointer_status}
        ready = all(value == "healthy" for value in checks.values())
        response.status_code = 200 if ready else 503
        return {"status": "ready" if ready else "not_ready", "checks": checks}

    return app


app = create_app()
