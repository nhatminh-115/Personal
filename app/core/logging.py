"""Structured logging with contextual tracing and secret masking."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# Sensitive patterns that must never be leaked in logs
SENSITIVE_KEYS = {"api_key", "secret", "password", "token", "authorization"}


def mask_sensitive_data(data: Any) -> Any:
    """Recursively mask sensitive values in dictionaries and lists."""
    if isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            if any(s in k.lower() for s in SENSITIVE_KEYS):
                masked[k] = "******"
            else:
                masked[k] = mask_sensitive_data(v)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item) for item in data]
    return data


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include custom extra attributes if present
        for key in ("run_id", "session_id", "event_type", "details"):
            if hasattr(record, key):
                val = getattr(record, key)
                log_payload[key] = mask_sensitive_data(val)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload)


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configures root logger with structured output."""
    logger = logging.getLogger("aura")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Avoid duplicate handlers if setup is called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(handler)

    # Prevent propagation to root logger to avoid double logging
    logger.propagate = False
    return logger


logger = setup_logging()
