"""Security middleware: headers, body size limit, raw mode kill-switch.

Apply at app-level via `app.middleware("http")` decorator (or
`app.add_middleware`). Order matters: body size first (reject early), then
raw filter, then add response headers.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import ALLOWED_ORIGINS, ENABLE_RAW, MAX_BODY_SIZE


SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "X-XSS-Protection": "0",
    # CSP yang reasonably tight untuk JSON API + docs UI single-page (React via babel-standalone).
    # Allow inline + unpkg/google fonts hanya untuk docs UI; production deployment yg punya domain
    # sendiri sebaiknya custom lewat reverse proxy.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
        "connect-src 'self'; "
        "worker-src 'self' blob:; "
        "frame-ancestors 'none'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject standard security headers ke setiap response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class BodySizeLimitMiddleware:
    """Pure ASGI middleware: reject request body > MAX_BODY_SIZE.

    Implemented as raw ASGI (not BaseHTTPMiddleware) karena BaseHTTPMiddleware
    punya known issue: stream consumption di dispatch() tidak ke-propagate ke
    downstream FastAPI body parser. Pure ASGI wraps receive callable di scope,
    sehingga downstream handler bisa baca body normal.

    Strategi:
        1. Cek Content-Length header — reject early kalau declared > cap.
        2. Wrap receive() untuk count bytes saat downstream consume body.

    Path media upload (`/2/media/upload`) pakai cap terpisah `MEDIA_UPLOAD_MAX_BYTES`.
    """

    SKIP_BUFFER_PREFIXES = (
        "/2/media/upload",
        "/2/chat/media/upload",
    )
    MEDIA_MAX_BYTES = int(os.environ.get("MEDIA_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_SIZE) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_media = any(path.startswith(p) for p in self.SKIP_BUFFER_PREFIXES)
        cap = self.MEDIA_MAX_BYTES if is_media else self.max_bytes

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > cap:
            await _send_too_large(send, cap)
            return

        method = scope.get("method", "GET")
        if method not in ("POST", "PUT", "PATCH") or is_media:
            await self.app(scope, receive, send)
            return

        received = 0
        too_large = False

        async def wrapped_receive() -> Message:
            nonlocal received, too_large
            msg = await receive()
            if msg["type"] == "http.request":
                body = msg.get("body", b"") or b""
                received += len(body)
                if received > cap:
                    too_large = True
            return msg

        response_started = False

        async def wrapped_send(msg: Message) -> None:
            nonlocal response_started
            if too_large and not response_started:
                response_started = True
                await _send_too_large(send, cap)
                return
            if msg["type"] == "http.response.start":
                response_started = True
            await send(msg)

        await self.app(scope, wrapped_receive, wrapped_send)


def _too_large(max_bytes: int) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={
            "errors": [{
                "title": "Payload Too Large",
                "detail": f"request body exceeds {max_bytes} bytes",
                "type": "payload_too_large",
                "status": 413,
            }]
        },
    )


async def _send_too_large(send: Send, max_bytes: int) -> None:
    """ASGI-level 413 response (no Request object available)."""
    import json as _json
    body = _json.dumps({
        "errors": [{
            "title": "Payload Too Large",
            "detail": f"request body exceeds {max_bytes} bytes",
            "type": "payload_too_large",
            "status": 413,
        }]
    }).encode()
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json")],
    })
    await send({"type": "http.response.body", "body": body, "more_body": False})


class RawModeKillSwitchMiddleware(BaseHTTPMiddleware):
    """Disable `?raw=1` query param di prod (env ENABLE_RAW=0).

    raw=1 mengembalikan payload mentah X termasuk cookie dump. Useful untuk
    debug, tapi kalau URL ke-share/log → leak credential.
    """

    async def dispatch(self, request: Request, call_next):
        if not ENABLE_RAW and request.query_params.get("raw") not in (None, "0", ""):
            return JSONResponse(
                status_code=403,
                content={
                    "errors": [{
                        "title": "Forbidden",
                        "detail": "raw mode disabled in this environment",
                        "type": "forbidden",
                        "status": 403,
                    }]
                },
            )
        return await call_next(request)


def install_security_middleware(app: FastAPI) -> None:
    """Wire security middlewares to the app. Call once after FastAPI init.

    Order (outermost → innermost):
        1. CORSMiddleware             (preflight handling, set CORS headers)
        2. SecurityHeadersMiddleware  (selalu add headers, even on error)
        3. BodySizeLimitMiddleware    (reject big request early)
        4. RawModeKillSwitchMiddleware
    """
    app.add_middleware(RawModeKillSwitchMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    if ALLOWED_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(ALLOWED_ORIGINS),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Admin-Token"],
            max_age=600,
        )
