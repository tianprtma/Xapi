"""Security middleware: headers, body size limit, raw mode kill-switch,
rate limiting.

Apply at app-level via `app.middleware("http")` decorator (or
`app.add_middleware`). Order matters: body size first (reject early), then
raw filter, then rate limit, then add response headers.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import ALLOWED_ORIGINS, ENABLE_RAW, MAX_BODY_SIZE


STRICT_CSP: bool = os.environ.get("STRICT_CSP", "0").strip().lower() in ("1", "true", "yes")

_DEV_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none'"
)

_STRICT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "font-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "worker-src 'self'; "
    "frame-ancestors 'none'"
)

SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "X-XSS-Protection": "0",
    "Content-Security-Policy": _STRICT_CSP if STRICT_CSP else _DEV_CSP,
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
        if method not in ("POST", "PUT", "PATCH"):
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
    from .errors import build_error
    return JSONResponse(
        status_code=413,
        content=build_error("VALIDATION_BODY_SIZE", max_bytes=max_bytes),
    )


async def _send_too_large(send: Send, max_bytes: int) -> None:
    """ASGI-level 413 response (no Request object available)."""
    import json as _json
    from .errors import build_error
    body = _json.dumps(build_error("VALIDATION_BODY_SIZE", max_bytes=max_bytes)).encode()
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
            from .errors import build_error
            return JSONResponse(
                status_code=403,
                content=build_error("INFRA_RAW_DISABLED"),
            )
        return await call_next(request)


# ──────────────────────────── Rate limiter ────────────────────────────


# Token bucket: default 100 req/s per token, burst 200.
RATE_LIMIT_PER_TOKEN: int = int(os.environ.get("RATE_LIMIT_PER_TOKEN", "100"))
RATE_LIMIT_BURST: int = int(os.environ.get("RATE_LIMIT_BURST", "200"))
# Max distinct tokens tracked in the bucket store (LRU eviction on overflow).
RATE_LIMIT_MAX_TOKENS: int = int(os.environ.get("RATE_LIMIT_MAX_TOKENS", "10000"))


class _Bucket:
    __slots__ = ("tokens", "last_refill", "burst")

    def __init__(self, burst: int) -> None:
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self.burst = burst


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-token token-bucket rate limiter.

    Keys on hashed auth_token (from Authorization header or ?auth_token=
    query). Buckets are bounded LRU to avoid memory exhaustion from
    spoofed tokens.
    """

    _instance: "RateLimitMiddleware | None" = None

    @classmethod
    def get(cls) -> "RateLimitMiddleware | None":
        return cls._instance

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._rate = float(RATE_LIMIT_PER_TOKEN)
        self._burst = RATE_LIMIT_BURST
        self._max = RATE_LIMIT_MAX_TOKENS
        self._lock = __import__("asyncio").Lock()
        RateLimitMiddleware._instance = self

    def _key(self, request: Request) -> str | None:
        from .auth import extract_bearer

        try:
            tok = extract_bearer(
                request.headers.get("Authorization"),
                request.query_params.get("auth_token"),
            )
        except HTTPException:
            # Token format invalid — use IP-based key.
            return f"ip:{request.client.host}" if request.client else "unknown"
        except Exception:  # noqa: BLE001
            return f"ip:{request.client.host}" if request.client else "unknown"

        if not tok:
            return f"ip:{request.client.host}" if request.client else "unknown"
        # Use same salted hash as everywhere else (config.token_key).
        from .config import token_key
        return token_key(tok)

    async def dispatch(self, request: Request, call_next):
        import asyncio as _asyncio

        key = self._key(request)
        async with self._lock:
            now = time.monotonic()
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(self._burst)
                self._buckets[key] = bucket
                # Evict LRU if over capacity
                while len(self._buckets) > self._max:
                    self._buckets.popitem(last=False)
            else:
                self._buckets.move_to_end(key)

            # Refill
            elapsed = now - bucket.last_refill
            bucket.tokens = min(float(bucket.burst), bucket.tokens + elapsed * self._rate)
            bucket.last_refill = now

            if bucket.tokens < 1.0:
                deficit = max(0.0, 1.0 - bucket.tokens)
                retry_after = max(5, int(deficit / self._rate))
                from .errors import build_error
                return JSONResponse(
                    status_code=429,
                    content=build_error("RATE_LIMIT_EXCEEDED", retry_after=retry_after),
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.tokens -= 1.0

        return await call_next(request)

    async def stats(self) -> dict:
        import asyncio as _asyncio
        async with self._lock:
            return {
                "active_buckets": len(self._buckets),
                "max_buckets": self._max,
                "rate_per_second": self._rate,
                "burst": self._burst,
            }


# ──────────────────────────── Content-Type validation ────────────────────────────


class ContentTypeValidationMiddleware(BaseHTTPMiddleware):
    """Reject POST/PUT/PATCH on /2/ paths with non-JSON Content-Type.

    Skips media upload paths (multipart), /login (form-encoded), /search.
    """

    SKIP_PATHS = frozenset({
        "/2/media/upload",
        "/2/chat/media/upload",
        "/login",
        "/search",
        "/admin/xchat/config",
    })
    ALLOWED_TYPES = {"application/json", "multipart/form-data", "application/x-www-form-urlencoded"}

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            path = request.url.path
            # Skip media upload / login / admin paths
            if not any(path.startswith(p) for p in self.SKIP_PATHS):
                ct = (request.headers.get("content-type") or "").lower().split(";")[0].strip()
                if ct and ct not in self.ALLOWED_TYPES:
                    from .errors import build_error
                    return JSONResponse(
                        status_code=415,
                        content=build_error(
                            "VALIDATION_INVALID_PARAM",
                            param="content-type",
                            reason=f"expected application/json, got {ct}",
                        ),
                    )
        return await call_next(request)


def install_security_middleware(app: FastAPI) -> None:
    """Wire security middlewares to the app. Call once after FastAPI init.

    Order (outermost → innermost):
        1. CORSMiddleware             (preflight handling, set CORS headers)
        2. SecurityHeadersMiddleware  (selalu add headers, even on error)
        3. RateLimitMiddleware        (per-token token bucket)
        4. QueryParamSanitizerMiddleware (scrub free-text query params)
        5. BodySizeLimitMiddleware    (reject big request early)
        6. RawModeKillSwitchMiddleware
    """
    app.add_middleware(RawModeKillSwitchMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    from .sanitize import QueryParamSanitizerMiddleware
    app.add_middleware(QueryParamSanitizerMiddleware)
    # Content-Type validation — reject non-JSON bodies on write endpoints
    app.add_middleware(ContentTypeValidationMiddleware)
    app.add_middleware(RateLimitMiddleware)
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
