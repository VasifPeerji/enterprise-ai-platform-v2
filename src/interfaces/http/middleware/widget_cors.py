"""
Scoped CORS for the public widget surface.

The app already mounts a global ``CORSMiddleware`` with ``allow_credentials=True``
and a strict origin allow-list for its authenticated routes. That middleware
also intercepts *every* CORS preflight (``OPTIONS`` with
``Access-Control-Request-Method``) before routing, so a company origin hitting
``/widget/*`` would be rejected by it — and we cannot simply widen the global
list because ``allow_credentials=True`` + ``*`` is invalid and would weaken the
authenticated surface.

The fix is this thin middleware, registered **last** so it sits *outermost*. It
acts only on ``/widget/*``: it answers preflight itself and reflects the request
``Origin`` with ``Access-Control-Allow-Credentials: false`` (credential-less is
what makes reflecting arbitrary origins safe). Every other path it passes
straight through, untouched, to the existing strict CORS. Reflecting any origin
here is deliberate: the public surface exposes only branding + a per-bot
origin-enforced, rate-limited chat endpoint, so the authoritative gate lives in
the handler, not in the browser-side CORS headers.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class PublicWidgetCORSMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, path_prefix: str = "/widget") -> None:
        super().__init__(app)
        self.path_prefix = path_prefix

    def _cors_headers(self, origin: str | None, *, preflight: bool) -> dict[str, str]:
        headers: dict[str, str] = {"Vary": "Origin"}
        if origin:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "false"
        if preflight:
            headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            headers["Access-Control-Allow-Headers"] = "Content-Type"
            headers["Access-Control-Max-Age"] = "600"
        return headers

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not request.url.path.startswith(self.path_prefix):
            return await call_next(request)

        origin = request.headers.get("origin")

        # Answer preflight ourselves so the global strict CORS never sees it.
        if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
            return Response(status_code=200, headers=self._cors_headers(origin, preflight=True))

        response = await call_next(request)
        for key, value in self._cors_headers(origin, preflight=False).items():
            response.headers[key] = value
        return response
