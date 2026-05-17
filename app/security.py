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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

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
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
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


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request body > MAX_BODY_SIZE.

    Strategi double-guard:
        1. Cek Content-Length header — reject early kalau declared > max.
        2. Stream-baca body, count bytes, abort kalau exceed (catch chunked
           transfer-encoding yang tidak set Content-Length).

    Path media upload (`/2/media/upload`) di-skip dari buffer step ke-2 —
    biarin handler stream langsung ke X (multipart upload). Tetap ada cap
    via Content-Length dengan limit terpisah `MEDIA_UPLOAD_MAX_BYTES`.
    """

    SKIP_BUFFER_PREFIXES = (
        "/2/media/upload",
        "/2/chat/media/upload",
    )
    # Per-path max bytes (Content-Length cap). Default 50MB untuk media.
    MEDIA_MAX_BYTES = int(os.environ.get("MEDIA_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_SIZE) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        is_media = any(path.startswith(p) for p in self.SKIP_BUFFER_PREFIXES)
        cap = self.MEDIA_MAX_BYTES if is_media else self.max_bytes

        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > cap:
            return _too_large(cap)

        # Media path: skip stream-buffer (handler bakal consume body langsung).
        if is_media:
            return await call_next(request)

        # Chunked or no Content-Length: stream-count.
        if request.method in ("POST", "PUT", "PATCH"):
            received = 0
            chunks: list[bytes] = []
            async for chunk in request.stream():
                received += len(chunk)
                if received > cap:
                    return _too_large(cap)
                chunks.append(chunk)
            body = b"".join(chunks)

            # Replay body untuk downstream consumer (FastAPI body parser).
            async def _receive():
                return {"type": "http.request", "body": body, "more_body": False}
            request = Request(request.scope, _receive)
        return await call_next(request)


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
