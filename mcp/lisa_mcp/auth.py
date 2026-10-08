# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""API key authentication for the remote (SSE/HTTP) deployment mode."""

from __future__ import annotations

import secrets
from typing import Any, Awaitable, Callable

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

# Load balancers probe this before they can supply a key.
_UNAUTHENTICATED_PATHS = frozenset({"/health"})


class ApiKeyMiddleware:
    """Reject HTTP requests whose ``X-API-Key`` header does not match.

    Implemented as raw ASGI so the module imports without Starlette present —
    the SSE dependencies are optional.
    """

    def __init__(self, app: Any, api_key: str) -> None:
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in _UNAUTHENTICATED_PATHS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        provided = headers.get(b"x-api-key", b"")
        # Constant-time comparison so a wrong key leaks no timing information.
        if not secrets.compare_digest(provided, self.api_key.encode()):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"error": "missing or invalid X-API-Key header"}',
                }
            )
            return

        await self.app(scope, receive, send)
