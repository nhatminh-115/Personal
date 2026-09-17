"""Base classes and contracts for tools."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.models.base import ToolDefinition


class RiskLevel(str, Enum):
    """Operational risk level of a tool."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolResult(BaseModel):
    """Standardized result returned by tool execution."""

    success: bool
    output: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Tool(ABC):
    """Abstract interface for all AURA tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def required_capabilities(self) -> List[str]:
        pass

    @property
    @abstractmethod
    def risk_level(self) -> RiskLevel:
        pass

    @property
    @abstractmethod
    def parameters_schema(self) -> Dict[str, Any]:
        """JSON Schema dictionary describing parameters."""
        pass

    @abstractmethod
    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        """Execute the tool safely and return a ToolResult."""
        pass

    def to_tool_definition(self) -> ToolDefinition:
        """Convert to normalized tool definition for LLM prompting."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )
