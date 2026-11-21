"""FastAPI server application initialization."""

import asyncio
from contextlib import asynccontextmanager, suppress
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
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


from app.orchestrator.graph import close_checkpointer, init_checkpointer, is_checkpointer_available


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    # Ensure database schema is initialized
    await init_db()
    # Ensure persistent checkpointer is initialized
    await init_checkpointer()

    # Reconcile idle root runs before serving requests. Ambiguous checkpoints
    # are closed as interrupted instead of replaying tools or memory writes.
    recovery_task = None
    try:
        from app.api.run_recovery import recover_running_root_runs, run_root_recovery_loop

        recovery_task = asyncio.create_task(run_root_recovery_loop())
        recovery_counts = await recover_running_root_runs()
        if any(recovery_counts.get(key, 0) for key in ("waiting", "terminal", "interrupted", "cancelled")):
            logger.info("Startup root-run recovery completed.", extra=recovery_counts)
    except Exception as exc:
        logger.error(
            "Startup root-run recovery failed (error type: %s); continuing with API startup.",
            type(exc).__name__,
        )

    # Discover and register local and cloud model providers dynamically
    try:
        from app.models.discovery import model_discovery_service
        await model_discovery_service.register_discovered_providers()
    except Exception as exc:
        logger.warning(
            "Non-fatal error during model discovery (error type: %s).",
            type(exc).__name__,
        )

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
    except Exception as exc:
        logger.warning(
            "Non-fatal error during startup MCP tool loading/discovery (error type: %s).",
            type(exc).__name__,
        )

    from app.events.runtime import start_automation_runtime

    stop_automation_runtime = await start_automation_runtime()

    try:
        yield
    finally:
        logger.info(f"Shutting down {settings.APP_NAME}")
        if recovery_task is not None:
            recovery_task.cancel()
            with suppress(asyncio.CancelledError):
                await recovery_task
        await stop_automation_runtime()
        try:
            from app.mcp.manager import mcp_manager
            await mcp_manager.disconnect_all()
        except Exception as exc:
            logger.warning(
                "Error disconnecting MCP servers on shutdown (error type: %s).",
                type(exc).__name__,
            )

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
        allow_headers=["Content-Type", "Authorization", "X-Aura-Event-Id"],
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

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        """Keep Pydantic's validation details without echoing submitted values."""
        safe_errors = []
        for error in exc.errors():
            if not isinstance(error, dict):
                continue
            raw_location = error.get("loc")
            location = []
            if isinstance(raw_location, (list, tuple)):
                location = [
                    part for part in raw_location
                    if isinstance(part, (str, int)) and not isinstance(part, bool)
                ][:16]
            safe_errors.append(
                {
                    "loc": location,
                    "msg": error.get("msg") if isinstance(error.get("msg"), str) else "Invalid request.",
                    "type": error.get("type") if isinstance(error.get("type"), str) else "request_validation_error",
                }
            )

        if not safe_errors:
            safe_errors.append({
                "loc": ["request"],
                "msg": "Request validation failed.",
                "type": "request_validation_error",
            })
        return JSONResponse(status_code=422, content={"detail": safe_errors})

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

        checkpointer_status = "healthy" if await is_checkpointer_available() else "unavailable"
        checks = {"database": database_status, "checkpointer": checkpointer_status}
        ready = all(value == "healthy" for value in checks.values())
        response.status_code = 200 if ready else 503
        return {"status": "ready" if ready else "not_ready", "checks": checks}

    return app


app = create_app()

