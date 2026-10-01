"""MCP Client Manager coordinating server connections, tool discovery, and failure-isolated dispatch."""

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
import httpx2

from app.capabilities.registry import CapabilityProviderHealth, CapabilityProviderMetadata
from app.core.errors import AURAError
from app.core.logging import logger
from app.mcp.adapter import MCPToolAdapter
from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.policy import MCPSecurityPolicy, mcp_security_policy
from app.tools.base import ToolResult
from app.tools.registry import ToolRegistry, tool_registry


class MCPServerError(AURAError):
    """Raised when an MCP server encounters an operational failure."""
    pass


class MCPClientManager:
    """
    Manages external Model Context Protocol (MCP) servers:
    - Handles lifecycle across stdio and SSE transports.
    - Dynamically discovers and registers tools into AURA's ToolRegistry.
    - Implements strict server-level crash and fault isolation.
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        policy: Optional[MCPSecurityPolicy] = None,
    ) -> None:
        self.registry = registry or tool_registry
        self.policy = policy or mcp_security_policy
        self._servers: Dict[str, MCPServerConfig] = {}
        self._discovered_tools: Dict[str, List[MCPToolAdapter]] = {}

    def register_server(self, config: MCPServerConfig) -> None:
        """Register an MCP server configuration."""
        # Configs contain mutable collections even when callers treat them as
        # immutable. Keep manager policy isolated from registration inputs.
        stored_config = config.model_copy(deep=True)
        self._servers[stored_config.id] = stored_config
        self._sync_provider_metadata(
            stored_config,
            CapabilityProviderHealth.UNKNOWN if stored_config.enabled else CapabilityProviderHealth.DISABLED,
        )
        logger.info(
            f"Registered MCP server '{stored_config.id}' (transport: {stored_config.transport.value})",
            extra={"server_id": stored_config.id, "transport": stored_config.transport.value},
        )

    def unregister_server(self, server_id: str) -> None:
        """Unregister an MCP server and remove its tools from registry."""
        if server_id in self._servers:
            # Remove any tools registered from this server
            if server_id in self._discovered_tools:
                for tool in self._discovered_tools[server_id]:
                    # Remove from registry if supported
                    if hasattr(self.registry, "_tools") and tool.name in self.registry._tools:
                        del self.registry._tools[tool.name]
                del self._discovered_tools[server_id]
            del self._servers[server_id]
            self.registry.unregister_capability_provider(f"mcp.{server_id}")
            logger.info(f"Unregistered MCP server '{server_id}'", extra={"server_id": server_id})

    def _sync_provider_metadata(
        self,
        config: MCPServerConfig,
        health: CapabilityProviderHealth,
        discovered_tool_names: Optional[set[str]] = None,
    ) -> None:
        """Expose declared, sanitized MCP provider facts without exposing credentials or endpoints."""
        capability_tools: Dict[str, List[str]] = {}
        for mcp_tool_name, capabilities in config.capabilities_by_tool.items():
            canonical_name = f"mcp_{config.id}_{mcp_tool_name}"
            # A declaration is configuration only. Bind it to runtime capabilities
            # after tools/list confirms that the provider actually exposes it.
            if discovered_tool_names is None or canonical_name not in discovered_tool_names:
                continue
            for capability in capabilities:
                capability_tools.setdefault(capability, []).append(canonical_name)
        metadata = CapabilityProviderMetadata(
            provider_id=f"mcp.{config.id}",
            name=config.name,
            version=config.provider_version,
            health=health,
            health_checked_at=datetime.now(timezone.utc) if health in {
                CapabilityProviderHealth.HEALTHY,
                CapabilityProviderHealth.DEGRADED,
                CapabilityProviderHealth.UNAVAILABLE,
            } else None,
            enabled=config.enabled,
            capabilities=list(dict.fromkeys(cap for caps in config.capabilities_by_tool.values() for cap in caps)),
            privacy_boundary=config.privacy_boundary,
            network_requirement=config.network_requirement,
            data_touched=config.data_touched,
            permissions=config.permissions,
            approval_requirement=config.approval_requirement,
        )
        self.registry.capability_providers.register(metadata, capability_tools)

    def get_server_config(self, server_id: str) -> Optional[MCPServerConfig]:
        """Retrieve server configuration by ID."""
        config = self._servers.get(server_id)
        return config.model_copy(deep=True) if config else None

    def list_servers(self) -> List[MCPServerConfig]:
        """List all configured MCP servers."""
        return [config.model_copy(deep=True) for config in self._servers.values()]

    SAFE_ENV_VARS = {
        "PATH",
        "Path",
        "PATHEXT",
        "SYSTEMROOT",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "LANG",
        "LC_ALL",
        "HOME",
        "USERPROFILE",
    }

    async def _create_stdio_params(self, config: MCPServerConfig) -> StdioServerParameters:
        """Construct StdioServerParameters with strict environment variable isolation."""
        # Whitelist safe system variables to prevent leaking ambient secrets/keys
        env = {k: v for k, v in os.environ.items() if k in self.SAFE_ENV_VARS}
        # Apply explicitly configured environment variables
        env.update(config.env)
        # Ensure PYTHONPATH includes workspace root so local fixture servers can import project modules if not set
        if "PYTHONPATH" not in env:
            env["PYTHONPATH"] = os.path.abspath(".")

        command = config.command or sys.executable
        return StdioServerParameters(
            command=command,
            args=config.args,
            env=env,
            cwd=config.cwd,
        )

    async def discover_tools(self, server_id: str) -> List[MCPToolAdapter]:
        """
        Connect to an MCP server, query available tools via tools/list,
        apply AURA's local security policy overlay, and register into ToolRegistry.
        """
        config = self._servers.get(server_id)
        if not config:
            raise MCPServerError(f"MCP server '{server_id}' is not registered.")
        if not config.enabled:
            logger.warning(f"MCP server '{server_id}' is disabled. Skipping tool discovery.")
            return []

        logger.info(f"Discovering tools on MCP server '{server_id}'...", extra={"server_id": server_id})
        adapters: List[MCPToolAdapter] = []

        try:
            if config.transport == MCPTransportType.STDIO:
                params = await self._create_stdio_params(config)
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await asyncio.wait_for(session.initialize(), timeout=config.timeout_seconds)
                        tools_result = await asyncio.wait_for(session.list_tools(), timeout=config.timeout_seconds)
                        raw_tools = tools_result.tools
            elif config.transport in {MCPTransportType.STREAMABLE_HTTP, MCPTransportType.HTTP}:
                if not config.url:
                    raise MCPServerError(f"MCP server '{server_id}' requires a valid URL for Streamable HTTP transport.")
                async with httpx2.AsyncClient(headers=config.headers or {}, timeout=config.timeout_seconds) as http_client:
                    async with streamable_http_client(config.url, http_client=http_client) as (read, write):
                        async with ClientSession(read, write) as session:
                            await asyncio.wait_for(session.initialize(), timeout=config.timeout_seconds)
                            tools_result = await asyncio.wait_for(session.list_tools(), timeout=config.timeout_seconds)
                            raw_tools = tools_result.tools
            elif config.transport == MCPTransportType.SSE:
                if not config.url:
                    raise MCPServerError(f"MCP server '{server_id}' requires a valid URL for legacy SSE transport.")
                async with sse_client(config.url, headers=config.headers) as (read, write):
                    async with ClientSession(read, write) as session:
                        await asyncio.wait_for(session.initialize(), timeout=config.timeout_seconds)
                        tools_result = await asyncio.wait_for(session.list_tools(), timeout=config.timeout_seconds)
                        raw_tools = tools_result.tools
            else:
                raise MCPServerError(f"Unsupported MCP transport '{config.transport}' for server '{server_id}'.")

            # Process discovered tools
            for t in raw_tools:
                tool_name = t.name
                # Check whitelist filter if configured
                if config.allowed_tools is not None and tool_name not in config.allowed_tools:
                    logger.debug(f"Skipping tool '{tool_name}' on server '{server_id}' (not in allowed_tools).")
                    continue

                tool_desc = t.description or ""
                input_schema = t.input_schema if hasattr(t, "input_schema") else {}

                # Evaluate AURA security policy overlay
                risk_level, required_caps = self.policy.evaluate_tool_security(
                    server_config=config,
                    tool_name=tool_name,
                    description=tool_desc,
                )

                adapter = MCPToolAdapter(
                    server_id=server_id,
                    mcp_tool_name=tool_name,
                    description=tool_desc,
                    input_schema=input_schema or {},
                    risk_level=risk_level,
                    required_capabilities=required_caps,
                    manager=self,
                    policy=self.policy,
                )
                self.registry.register(adapter)
                adapters.append(adapter)

            self._discovered_tools[server_id] = adapters
            discovered_names = {adapter.name for adapter in adapters}
            missing_declared_tools = set(config.capabilities_by_tool) - {adapter.mcp_tool_name for adapter in adapters}
            self._sync_provider_metadata(
                config,
                CapabilityProviderHealth.DEGRADED if missing_declared_tools else CapabilityProviderHealth.HEALTHY,
                discovered_names,
            )
            logger.info(
                f"Successfully registered {len(adapters)} tools from MCP server '{server_id}'.",
                extra={"server_id": server_id, "tools_count": len(adapters)},
            )
            return adapters

        except Exception as e:
            self._sync_provider_metadata(config, CapabilityProviderHealth.UNAVAILABLE)
            logger.error(
                f"Server-level failure during tool discovery on MCP server '{server_id}': {e}",
                exc_info=True,
                extra={"server_id": server_id},
            )
            # Crash isolation: do not raise, return empty list to protect the agent runtime
            return []

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> ToolResult:
        """
        Execute an MCP tool on the target server with timeout enforcement
        and comprehensive failure isolation.
        """
        config = self._servers.get(server_id)
        if not config:
            return ToolResult(
                success=False,
                output="",
                error=f"MCP server '{server_id}' is not registered.",
                metadata={"error_category": "server_not_found", "server_id": server_id},
            )
        if not config.enabled:
            return ToolResult(
                success=False,
                output="",
                error=f"MCP server '{server_id}' is disabled.",
                metadata={"error_category": "server_disabled", "server_id": server_id},
            )

        try:
            if config.transport == MCPTransportType.STDIO:
                params = await self._create_stdio_params(config)
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await asyncio.wait_for(session.initialize(), timeout=config.timeout_seconds)
                        res = await asyncio.wait_for(
                            session.call_tool(tool_name, arguments or {}),
                            timeout=config.timeout_seconds,
                        )
            elif config.transport in {MCPTransportType.STREAMABLE_HTTP, MCPTransportType.HTTP}:
                if not config.url:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Missing URL for MCP server '{server_id}'.",
                        metadata={"error_category": "invalid_configuration", "server_id": server_id},
                    )
                async with httpx2.AsyncClient(headers=config.headers or {}, timeout=config.timeout_seconds) as http_client:
                    async with streamable_http_client(config.url, http_client=http_client) as (read, write):
                        async with ClientSession(read, write) as session:
                            await asyncio.wait_for(session.initialize(), timeout=config.timeout_seconds)
                            res = await asyncio.wait_for(
                                session.call_tool(tool_name, arguments or {}),
                                timeout=config.timeout_seconds,
                            )
            elif config.transport == MCPTransportType.SSE:
                if not config.url:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Missing URL for MCP server '{server_id}'.",
                        metadata={"error_category": "invalid_configuration", "server_id": server_id},
                    )
                async with sse_client(config.url, headers=config.headers) as (read, write):
                    async with ClientSession(read, write) as session:
                        await asyncio.wait_for(session.initialize(), timeout=config.timeout_seconds)
                        res = await asyncio.wait_for(
                            session.call_tool(tool_name, arguments or {}),
                            timeout=config.timeout_seconds,
                        )
            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Unsupported transport '{config.transport}' for server '{server_id}'.",
                    metadata={"error_category": "unsupported_transport", "server_id": server_id},
                )

            # Format tool call response
            output_parts = []
            for c in (res.content or []):
                if hasattr(c, "text"):
                    output_parts.append(str(c.text))
                elif isinstance(c, dict) and "text" in c:
                    output_parts.append(str(c["text"]))
                else:
                    output_parts.append(str(c))
            output_text = "\n".join(output_parts)

            is_error = getattr(res, "is_error", False) or getattr(res, "isError", False)
            if is_error:
                return ToolResult(
                    success=False,
                    output=output_text,
                    error=output_text or "MCP tool returned error status.",
                    metadata={"server_id": server_id, "tool_name": tool_name},
                )

            return ToolResult(
                success=True,
                output=output_text,
                error=None,
                metadata={"server_id": server_id, "tool_name": tool_name},
            )

        except asyncio.TimeoutError:
            err_msg = f"MCP tool '{tool_name}' on server '{server_id}' timed out after {config.timeout_seconds}s."
            logger.error(err_msg, extra={"server_id": server_id, "tool_name": tool_name})
            return ToolResult(
                success=False,
                output="",
                error=err_msg,
                metadata={"error_category": "timeout", "server_id": server_id},
            )
        except Exception as e:
            err_msg = f"Server failure on MCP server '{server_id}': {str(e)}"
            logger.error(err_msg, exc_info=True, extra={"server_id": server_id, "tool_name": tool_name})
            return ToolResult(
                success=False,
                output="",
                error=err_msg,
                metadata={"error_category": "mcp_server_error", "server_id": server_id},
            )

    async def disconnect_all(self) -> None:
        """Clean up and unregister all discovered tools and server sessions."""
        for server_id in list(self._servers.keys()):
            self.unregister_server(server_id)
        logger.info("All MCP servers disconnected and unregistered.")


# Global singleton instance
mcp_manager = MCPClientManager()
