"""Shared keyset cursor helpers for bounded API collection reads."""

import base64
import json
from datetime import datetime, timezone
from typing import Callable, Sequence, TypeVar

from fastapi import HTTPException, Response

T = TypeVar("T")

MAX_COLLECTION_PAGE_SIZE = 500


def decode_timestamp_id_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        encoded = cursor + "=" * (-len(cursor) % 4)
        timestamp_text, record_id = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
        timestamp = datetime.fromisoformat(timestamp_text)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if not isinstance(record_id, str) or not record_id or len(record_id) > 36:
            raise ValueError("invalid record ID")
        return timestamp, record_id
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid pagination cursor.") from exc


def encode_timestamp_id_cursor(timestamp: datetime, record_id: str) -> str:
    payload = json.dumps([timestamp.isoformat(), record_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def set_next_cursor_header(
    response: Response,
    rows: Sequence[T],
    page_size: int,
    timestamp_for: Callable[[T], datetime],
    id_for: Callable[[T], str],
) -> list[T]:
    if len(rows) <= page_size:
        return list(rows)
    last_item = rows[page_size - 1]
    response.headers["X-Next-Cursor"] = encode_timestamp_id_cursor(
        timestamp_for(last_item), id_for(last_item),
    )
    return list(rows[:page_size])
