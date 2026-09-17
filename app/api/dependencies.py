"""FastAPI Dependency Injection providers."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.service import ApprovalService
from app.db.session import get_db
from app.memory.base import MemoryService
from app.memory.service import SQLMemoryService
from app.models.router import ModelRouter, model_router
from app.observability.tracer import TraceService
from app.tools.registry import ToolRegistry, tool_registry


def get_memory_service(db: AsyncSession = Depends(get_db)) -> MemoryService:
    return SQLMemoryService(db)


def get_approval_service(db: AsyncSession = Depends(get_db)) -> ApprovalService:
    return ApprovalService(db)


def get_trace_service(db: AsyncSession = Depends(get_db)) -> TraceService:
    return TraceService(db)


def get_tool_registry() -> ToolRegistry:
    return tool_registry


def get_model_router() -> ModelRouter:
    return model_router
