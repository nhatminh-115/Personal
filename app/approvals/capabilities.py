"""Granular capability definitions for tools and actions."""

from enum import Enum


class Capability(str, Enum):
    """Standardized capability taxonomy."""

    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    SHELL_EXECUTE = "shell.execute"
    NETWORK_ACCESS = "network.access"
    EMAIL_READ = "email.read"
    EMAIL_SEND = "email.send"
    GIT_READ = "git.read"
    GIT_WRITE = "git.write"
    MCP_READ = "mcp.read"
    MCP_EXECUTE = "mcp.execute"
    SANDBOX_EXECUTE = "sandbox.execute"
    AGENT_DELEGATE = "agent.delegate"

