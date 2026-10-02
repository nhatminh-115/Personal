"""Request body limits reject oversized payloads before application parsing."""

import httpx
import pytest
from starlette.responses import JSONResponse

from app.api.middleware import MAX_REQUEST_BODY_BYTES, RequestBodyLimitMiddleware
from app.api.server import create_app
from app.core.settings import settings


async def _consume_body_app(scope, receive, send):
    body = bytearray()
    while True:
        message = await receive()
        body.extend(message.get("body", b""))
        if not message.get("more_body", False):
            break
    await JSONResponse({"received": len(body)})(scope, receive, send)


async def _invoke(middleware, *, headers=(), chunks=()):
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]

    async def receive():
        return messages.pop(0)

    sent = []

    async def send(message):
        sent.append(message)

    await middleware({"type": "http", "method": "POST", "path": "/test", "headers": list(headers)}, receive, send)
    return sent


def _response_body(sent):
    return b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")


@pytest.mark.asyncio
async def test_content_length_over_limit_is_rejected_without_calling_app():
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    response = await _invoke(
        RequestBodyLimitMiddleware(app, max_body_bytes=4),
        headers=[(b"content-length", b"5")],
        chunks=[b"xxxxx"],
    )

    assert not called
    assert response[0]["status"] == 413
    assert b"4-byte limit" in _response_body(response)


@pytest.mark.asyncio
async def test_chunked_body_over_limit_is_rejected_before_app_receives_overflow_chunk():
    observed = []

    async def app(scope, receive, send):
        while True:
            message = await receive()
            observed.append(message["body"])
            if not message.get("more_body", False):
                break
        await JSONResponse({"ok": True})(scope, receive, send)

    response = await _invoke(
        RequestBodyLimitMiddleware(app, max_body_bytes=4),
        chunks=[b"123", b"456"],
    )

    assert observed == [b"123"]
    assert response[0]["status"] == 413


@pytest.mark.asyncio
async def test_body_at_limit_passes_through():
    response = await _invoke(
        RequestBodyLimitMiddleware(_consume_body_app, max_body_bytes=4),
        chunks=[b"12", b"34"],
    )

    assert response[0]["status"] == 200
    assert b'"received":4' in _response_body(response)


@pytest.mark.asyncio
async def test_create_app_rejects_oversized_content_length_and_keeps_cors_headers():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://aura.test") as client:
        response = await client.post(
            "/health",
            content=b"not parsed",
            headers={
                "Content-Length": str(MAX_REQUEST_BODY_BYTES + 1),
                "Origin": settings.CORS_ALLOWED_ORIGINS.split(",")[0].strip(),
            },
        )

    assert response.status_code == 413
    assert "access-control-allow-origin" in response.headers
