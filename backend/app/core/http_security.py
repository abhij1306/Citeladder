"""ASGI-level body limits and API cache-isolation headers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse

from app.core.config.http import API_REQUEST_BODY_MAX_BYTES

ASGIApp = Callable[
    [
        dict[str, Any],
        Callable[..., Awaitable[dict]],
        Callable[..., Awaitable[None]],
    ],
    Awaitable[None],
]


class RequestBodyLimitMiddleware:
    """Reject oversized API bodies before or while they are streamed."""

    def __init__(self, app: ASGIApp, max_bytes: int = API_REQUEST_BODY_MAX_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    @staticmethod
    def _declared_too_large(headers: dict[bytes, bytes], max_bytes: int) -> bool:
        declared = headers.get(b"content-length")
        if declared is None:
            return False
        if not declared or not all(ord("0") <= value <= ord("9") for value in declared):
            return True
        try:
            return int(declared) > max_bytes
        except ValueError:
            return True

    async def _limited_receive(
        self, receive: Callable, state: dict[str, int | bool]
    ) -> dict:
        message = await receive()
        if message.get("type") == "http.request":
            state["consumed"] = int(state["consumed"]) + len(message.get("body", b""))
            if int(state["consumed"]) > self.max_bytes:
                state["rejected"] = True
                return {"type": "http.disconnect"}
        return message

    async def __call__(
        self, scope: dict[str, Any], receive: Callable, send: Callable
    ) -> None:
        path = str(scope.get("path", ""))
        if scope.get("type") != "http" or not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        if self._declared_too_large(headers, self.max_bytes):
            await self._reject(scope, receive, send)
            return

        state: dict[str, int | bool] = {"consumed": 0, "rejected": False}

        async def guarded_send(message: dict) -> None:
            if not state["rejected"]:
                await send(message)

        try:
            await self.app(
                scope,
                lambda: self._limited_receive(receive, state),
                guarded_send,
            )
        except Exception:
            if not state["rejected"]:
                raise
        if state["rejected"]:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: dict, receive: Callable, send: Callable) -> None:
        response = JSONResponse({"detail": "Request body too large"}, status_code=413)
        await response(scope, receive, send)


class ApiNoStoreMiddleware:
    """Default API responses to no-store unless they opt into private caching."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(
        self, scope: dict[str, Any], receive: Callable, send: Callable
    ) -> None:
        path = str(scope.get("path", ""))
        is_api = scope.get("type") == "http" and path.startswith("/api/")

        async def add_headers(message: dict) -> None:
            if is_api and message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                private_cache = any(
                    key.lower() == b"cache-control"
                    and value.lower().startswith(b"private, max-age=")
                    for key, value in headers
                )
                if not private_cache:
                    blocked = {b"cache-control", b"pragma", b"expires"}
                    headers = [
                        (key, value)
                        for key, value in headers
                        if key.lower() not in blocked
                    ]
                    headers.extend(
                        [
                            (b"cache-control", b"private, no-store, max-age=0"),
                            (b"pragma", b"no-cache"),
                            (b"expires", b"0"),
                        ]
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, add_headers)
