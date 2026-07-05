"""Structured JSON logging + request-id middleware + health endpoint.

Wire into app via ``install_observability(app)``. Produces JSON logs
that play nice with structured-log aggregators (Datadog, Grafana, ELK).

Request IDs: every request gets an ``X-Request-ID`` response header. If
the client sends one, it's echoed back; otherwise a UUIDv4 is generated.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


# ──────────────────────────── Structured log handler ────────────────────────────


class _JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects.

    Fields: timestamp, level, logger, message, and any extra dict.
    Set LOG_LEVEL env var to control (default INFO).
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        base: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            import traceback
            base["exc"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(base, default=str, ensure_ascii=False)


def _setup_logging() -> None:
    """Route all loggers to stdout as structured JSON."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)


# ──────────────────────────── Request ID middleware ────────────────────────────


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject ``X-Request-ID`` into every response.

    Reads from incoming ``X-Request-ID`` header if present (passthrough),
    otherwise generates a UUIDv4 short-id.
    """

    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or _uuid.uuid4().hex[:12]
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


# ──────────────────────────── Access log middleware ────────────────────────────


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Emit one JSON log line per request with method, path, status, duration_ms."""

    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        try:
            req_id = request.state.request_id
        except AttributeError:
            req_id = "-"
        logging.getLogger("xapi.access").info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "request_id": req_id,
            },
        )
        return response


# ──────────────────────────── Health endpoint ────────────────────────────


class HealthChecker:
    """Collect health checks from registered subsystems.

    Each check is ``async def check() -> (bool, str)`` where True = healthy.
    """

    _instance: "HealthChecker | None" = None

    def __init__(self) -> None:
        self._checks: dict[str, Any] = {}

    @classmethod
    def get(cls) -> "HealthChecker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, name: str, check_fn):
        self._checks[name] = check_fn

    async def run_all(self) -> dict[str, Any]:
        results = {}
        all_ok = True
        for name, check in self._checks.items():
            try:
                ok, detail = await check()
            except Exception as e:  # noqa: BLE001
                ok, detail = False, str(e)
            results[name] = {"healthy": ok, "detail": detail}
            if not ok:
                all_ok = False
        return {"healthy": all_ok, "checks": results}


async def _health_endpoint(request: Request) -> JSONResponse:
    from main import app, WORKER_ID  # type: ignore[import]
    hc = HealthChecker.get()
    result = await hc.run_all()
    result["service"] = app.title
    result["version"] = app.version
    result["worker_id"] = WORKER_ID
    status = 200 if result["healthy"] else 503
    return JSONResponse(status_code=status, content=result)


def install_observability(app: FastAPI) -> None:
    """Wire structured logging, request IDs, access log, and /health."""
    _setup_logging()

    # Order: outermost first
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # Register built-in health checks
    hc = HealthChecker.get()

    async def _session_cache_check():
        try:
            stats = await _get_store_stats() or {}
            return True, f"{stats.get('alive', 0)} alive / {stats.get('total', 0)} total"
        except Exception as e:
            return False, str(e)

    async def _client_pool_check():
        try:
            from app.client_pool import ClientPool
            stats = await ClientPool.get().stats()
            return True, f"{stats.get('size', 0)}/{stats.get('max', 0)} sessions"
        except Exception as e:
            return False, str(e)

    async def _tid_check():
        try:
            from tid_provider import TIDProvider
            stats = await TIDProvider.get().stats()
            # Healthy if loaded OR using fallback (still functional).
            # Pre-warm hasn't fired yet → loaded=False is also fine on cold start.
            ok = True
            if stats.get("fallback_mode"):
                detail = "fallback"
            elif stats.get("loaded"):
                detail = "ok"
            else:
                detail = "not yet loaded"
            return ok, detail
        except Exception as e:
            return False, str(e)

    async def _playwright_check():
        try:
            from playwright_search import PlaywrightPool
            pool = PlaywrightPool.get()
            bw = pool._browser
            if bw is None:
                return True, "not yet launched"
            return bw.is_connected(), "connected" if bw.is_connected() else "disconnected"
        except Exception as e:
            return False, str(e)

    hc.register("session_cache", _session_cache_check)
    hc.register("client_pool", _client_pool_check)
    hc.register("tid_provider", _tid_check)
    hc.register("playwright", _playwright_check)

    app.add_api_route("/health", _health_endpoint, methods=["GET"], include_in_schema=False, tags=["Infra"])


async def _get_store_stats():
    try:
        from session_cache import SessionStore
        return await SessionStore.get().stats()
    except Exception:  # noqa: BLE001
        return None
