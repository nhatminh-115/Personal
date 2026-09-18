"""Data models and configuration specifications for isolated execution sandboxes."""

import os
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SandboxConfig(BaseModel):
    """Hardened execution parameters for sandbox container runtime."""

    image: str = Field(
        default_factory=lambda: os.getenv("AURA_SANDBOX_IMAGE", "aura-coding-sandbox:latest"),
        description="Base container image.",
    )
    workspace_dir: str = Field(
        default_factory=lambda: str(
            os.getenv("AURA_WORKSPACE_ROOT")
            or getattr(__import__("app.core.settings", fromlist=["settings"]).settings, "AURA_WORKSPACE_ROOT", None)
            or os.path.abspath("./workspace")
        ),
        description="Host directory mounted into container.",
    )
    container_workspace_mount: str = Field(default="/workspace", description="Mount path inside container.")
    workdir: str = Field(default="/workspace", description="Working directory inside container.")
    user: str = Field(default="1000:1000", description="Non-root user ID and group ID.")
    read_only_root: bool = Field(default=True, description="Enforce read-only root filesystem.")
    network_disabled: bool = Field(default=True, description="Isolate container network completely.")
    memory_limit: str = Field(default="512m", description="Maximum memory allocation (e.g. 512m, 1g).")
    cpu_quota: float = Field(default=1.0, ge=0.1, le=4.0, description="CPU core quota allocated to container.")
    pids_limit: int = Field(default=64, ge=8, le=256, description="Maximum number of simultaneous processes/threads.")
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0, description="Execution timeout in seconds.")
    max_output_bytes: int = Field(default=100_000, ge=1024, le=10_000_000, description="Maximum byte length of captured stdout/stderr before truncation.")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables passed to container.")


class ExecutionResult(BaseModel):
    """Structured result from sandboxed command execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
