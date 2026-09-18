"""Configuration loader for Model Context Protocol (MCP) servers."""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import yaml

from app.core.logging import logger
from app.mcp.config import MCPServerConfig

# Pattern for ${VAR_NAME} or ${VAR_NAME:-default}
ENV_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")


def resolve_secrets(val: Any) -> Any:
    """
    Recursively resolve environment variable secret references (${VAR} or ${VAR:-default}).
    Only explicitly referenced environment variables are retrieved from the host.
    Raises ValueError if a referenced variable without default is not set.
    """
    if isinstance(val, str):
        def repl(match: re.Match) -> str:
            var_name = match.group(1)
            default_val = match.group(2)
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val
            if default_val is not None:
                return default_val
            raise ValueError(
                f"Missing required environment variable '{var_name}' referenced in MCP configuration."
            )
        return ENV_PATTERN.sub(repl, val)
    elif isinstance(val, dict):
        return {k: resolve_secrets(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [resolve_secrets(item) for item in val]
    return val


def load_mcp_servers_from_file(config_path: Union[str, Path]) -> List[MCPServerConfig]:
    """
    Load, substitute secrets, validate, and return MCP server definitions from a JSON or YAML file.
    If the file does not exist, logs a debug message and returns an empty list.
    """
    path = Path(config_path)
    if not path.exists():
        logger.debug(f"MCP configuration file not found at '{path}'; skipping MCP startup registration.")
        return []

    try:
        content = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            raw_data = yaml.safe_load(content)
        else:
            raw_data = json.loads(content)

        if not raw_data:
            return []

        # Resolve explicit secret variables in loaded raw data
        resolved_data = resolve_secrets(raw_data)

        # Parse either {"servers": [...]} or list directly [...]
        if isinstance(resolved_data, dict):
            servers_list = resolved_data.get("servers", [])
        elif isinstance(resolved_data, list):
            servers_list = resolved_data
        else:
            raise ValueError(
                f"Invalid MCP configuration root structure: expected list or object with 'servers' key, got {type(resolved_data).__name__}"
            )

        validated_configs: List[MCPServerConfig] = []
        for item in servers_list:
            if not isinstance(item, dict):
                continue
            validated_configs.append(MCPServerConfig(**item))

        logger.info(f"Loaded {len(validated_configs)} MCP server definition(s) from '{path}'.")
        return validated_configs

    except Exception as e:
        logger.error(f"Failed to load MCP server configuration from '{path}': {e}", exc_info=True)
        raise
