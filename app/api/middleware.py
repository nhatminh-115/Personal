"""ASGI middleware for API authentication and bounded request bodies."""

from collections.abc import Awaitable, Callable
import hmac
from typing import Any

from pydantic import SecretStr
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[dict[str, Any]]], Callable[..., Awaitable[None]]],
    Awaitable[None],
]
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024


class _RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Enforce a bounded request body for both fixed-length and streamed HTTP requests."""

    def __init__(self, app: ASGIApp, max_body_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = 0
            if declared_length > self.max_body_bytes:
                await self._reject(scope, receive, send)
                return

        received_bytes = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_body_bytes:
                    raise _RequestBodyTooLarge
            return message

        response_started = False

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if response_started:
                raise
            await self._reject(scope, receive, send)

    async def _reject(self, scope: dict[str, Any], receive, send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds the {self.max_body_bytes}-byte limit."},
        )
        await response(scope, receive, send)


class ApiNoStoreMiddleware:
    """Prevent HTTP caches from retaining private AURA API responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == "/v1" or path.startswith("/v1/")):
            await self.app(scope, receive, send)
            return

        async def no_store_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_message = dict(message)
                response_message["headers"] = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
                message = response_message
            await send(message)

        await self.app(scope, receive, no_store_send)


class ApiTokenAuthenticationMiddleware:
    """Require a configured shared bearer token on every non-probe HTTP route."""

    def __init__(self, app: ASGIApp, token_getter: Callable[[], SecretStr | str | None]) -> None:
        self.app = app
        self.token_getter = token_getter

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in {"/health", "/ready"}:
            await self.app(scope, receive, send)
            return

        path_parts = path.strip("/").split("/")
        is_signed_automation_webhook = (
            scope.get("method") == "POST"
            and len(path_parts) == 5
            and path_parts[0] == "v1"
            and path_parts[1] == "automations"
            and bool(path_parts[2])
            and path_parts[3:] == ["webhook", "events"]
        )
        if is_signed_automation_webhook:
            # The webhook handler validates its own per-automation bearer secret.
            await self.app(scope, receive, send)
            return

        configured = self.token_getter()
        expected = configured.get_secret_value() if isinstance(configured, SecretStr) else configured
        if not isinstance(expected, str) or not expected:
            await self.app(scope, receive, send)
            return

        authorization = Headers(scope=scope).get("authorization", "")
        scheme, separator, supplied = authorization.partition(" ")
        is_valid = (
            separator == " "
            and scheme.casefold() == "bearer"
            and bool(supplied)
            and supplied == supplied.strip()
            and hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
        )
        if is_valid:
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            status_code=401,
            content={
                "detail": {
                    "code": "api_auth_required",
                    "message": "A valid API bearer token is required.",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)

