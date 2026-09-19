"""Application settings and environment configuration."""

from pathlib import Path
from typing import Literal, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """AURA Application configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str = "AURA — Adaptive User Runtime Agent"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Database
    # Default to SQLite for easy local testability; override via .env with PostgreSQL + pgvector
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///aura.db",
        description="Async SQLAlchemy database URL (e.g. postgresql+asyncpg://aura:aura@localhost:5432/aura)",
    )
    DATABASE_ECHO: bool = False

    # Workspace & Sandbox
    AURA_WORKSPACE_ROOT: Path = Field(
        default=Path("./workspace").resolve(),
        description="Root directory for isolated agent workspace operations",
    )

    # LangGraph Checkpointing Database
    CHECKPOINT_DB_PATH: Path = Field(
        default=Path("./aura_checkpoints.db").resolve(),
        description="File path for durable LangGraph execution checkpoints",
    )

    # Checkpoint Security
    LANGGRAPH_STRICT_MSGPACK: bool = True

    # Model Provider Settings
    MODEL_PROVIDER: Literal["mock", "openai"] = "mock"
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL_NAME: str = "gpt-4o-mini"
    MODEL_TEMPERATURE: float = 0.0
    MODEL_MAX_TOKENS: int = 2048

    # Embedding Provider Settings
    EMBEDDING_PROVIDER: Literal["mock", "openai"] = "mock"
    EMBEDDING_MODEL_NAME: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536

    # Model Context Protocol (MCP) Settings
    MCP_CONFIG_PATH: Optional[Path] = Field(
        default=Path("./mcp_servers.json"),
        description="Path to MCP servers configuration file (JSON or YAML)",
    )

    # Research Provider Settings
    RESEARCH_PROVIDER_MODE: Literal["deterministic", "live"] = "deterministic"
    SEMANTIC_SCHOLAR_API_KEY: Optional[str] = None
    RESEARCH_HTTP_TIMEOUT_SECONDS: float = 30.0
    RESEARCH_MAX_PDF_BYTES: int = 15 * 1024 * 1024  # 15 MB
    RESEARCH_MAX_PDF_PAGES: int = 50
    RESEARCH_MAX_EXTRACTED_CHARS: int = 500_000
    ARXIV_MIN_REQUEST_INTERVAL_SECONDS: float = 3.0


# Singleton global settings instance
settings = Settings()

# Enforce LangGraph checkpoint security: restrict msgpack deserialization to SAFE_MSGPACK_TYPES
import os
if settings.LANGGRAPH_STRICT_MSGPACK:
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
