"""Response builders: convert client result dict → FastAPI JSONResponse.

3 styles:
- `wrap`        — pass-through (raw=1 mode)
- `finalize`    — read op: run formatter, return v2-shape data atau errors
- `write_finalize` — write op: balikin {data: <gql payload>} as-is
- `stub_501`    — generate Not Implemented response with reason
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi.responses import JSONResponse

from app.errors import build_error
from formatter import format_error


# ──────────────────────────── Wrappers ────────────────────────────

_SENSITIVE_KEYS = frozenset({"cookies", "tokens"})


def _strip_sensitive(result: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive fields from result dict — never send auth_token/cookies to client."""
    return {k: v for k, v in result.items() if k not in _SENSITIVE_KEYS}


def wrap(result: dict[str, Any]) -> JSONResponse:
    """Pass-through: HTTP code by status, body = raw result dict."""
    code_map = {"ok": 200, "valid": 200, "invalid": 401, "error": 502}
    return JSONResponse(status_code=code_map.get(result.get("status"), 500), content=_strip_sensitive(result))


def finalize(
    result: dict[str, Any],
    formatter: Callable[[dict[str, Any]], dict[str, Any]],
    raw: bool,
) -> JSONResponse:
    """Read endpoint finalizer.

    Convert hasil graphql_call/Playwright → format X API v2.
    Bila `raw=True`: skip formatter, return wrap(result) (full debug payload).
    """
    if raw:
        return wrap(result)

    if result.get("status") in ("ok", "valid"):
        formatted = formatter(result.get("data") or {})
        # Error sintaks dari GraphQL (formatter detect schema mismatch)?
        if "errors" in formatted and not formatted.get("data"):
            return JSONResponse(status_code=404, content=formatted)
        return JSONResponse(status_code=200, content=formatted)

    if result.get("status") == "invalid":
        http_status = result.get("http_status") or 401
        error_key = "UPSTREAM_AUTH_REJECTED" if http_status == 403 else "AUTH_TOKEN_EXPIRED"
        return JSONResponse(
            status_code=401,
            content=build_error(
                error_key,
                detail=result.get("error"),
                http_status=str(http_status),
                reason=str(result.get("error", "auth_token invalid/expired"))[:200],
            ),
        )

    return JSONResponse(
        status_code=502,
        content=build_error(
            "UPSTREAM_ERROR",
            detail=str(result.get("error") or "GraphQL call failed")[:500],
            http_status=str(result.get("http_status") or "unknown"),
            reason=str(result.get("error") or "upstream failure")[:200],
        ),
    )


def _first_upstream_error(payload: Any) -> Optional[dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    errors = payload.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    first = errors[0]
    return first if isinstance(first, dict) else {"message": str(first)}


def _has_success_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return bool(payload)
    data = payload.get("data")
    if not isinstance(data, dict):
        return bool(data)
    # None / {} / [] are empty values — no real data to show.
    # A response where ALL data fields are None/empty + has errors
    # should surface the error, not pretend success.
    return any(value not in ({}, [], None) for value in data.values())


def _upstream_error_status(error: dict[str, Any]) -> int:
    """Map X upstream error to HTTP status.

    Uses two strategies:
    1. Known error codes from X docs (https://developer.x.com/support/x-api/error-codes).
    2. Text substring matching on error fields as fallback.

    NOTE: X error codes are versioned per GQL op. This list may drift.
    """
    extensions = error.get("extensions")
    extension_code = extensions.get("code") if isinstance(extensions, dict) else None
    code = str(error.get("code") or extension_code or "")
    text = " ".join(
        str(error.get(key) or "")
        for key in ("name", "kind", "message")
    ).lower()
    # X error codes → HTTP 401
    if code in {"32", "64", "89", "99", "135", "136", "179", "220", "261", "353"}:
        return 401
    if any(w in text for w in ("permission", "authorization", "unauthorized", "not permitted", "permitted", "forbidden")):
        return 403
    # X error codes → HTTP 404
    if code in {"34", "50", "144"} or "not found" in text or "does not exist" in text:
        return 404
    if "validation" in text or "badrequest" in text or "bad request" in text:
        return 400
    return 502


def _upstream_error_response(error: dict[str, Any]) -> JSONResponse:
    status = _upstream_error_status(error)
    detail = str(error.get("message") or error)[:1000]
    content = build_error(
        "UPSTREAM_ERROR",
        detail=detail,
        http_status=str(status),
        reason=detail[:200],
    )
    content["errors"][0]["status"] = status
    return JSONResponse(status_code=status, content=content)


def write_finalize(
    result: dict[str, Any],
    raw: bool,
    formatter: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    success_status: int = 200,
) -> JSONResponse:
    """Write endpoint finalizer: balikin {data: <gql payload>} atau errors."""
    if raw:
        return wrap(result)
    if result.get("status") == "ok":
        payload = result.get("data")
        upstream_error = _first_upstream_error(payload)
        if upstream_error and not _has_success_payload(payload):
            return _upstream_error_response(upstream_error)
        content = formatter(payload or {}) if formatter else {"data": payload}
        return JSONResponse(status_code=success_status, content=content)
    if result.get("status") == "invalid":
        http_status = result.get("http_status") or 401
        error_key = "UPSTREAM_AUTH_REJECTED" if http_status == 403 else "AUTH_TOKEN_EXPIRED"
        return JSONResponse(
            status_code=401,
            content=build_error(
                error_key,
                detail=str(result.get("error") or "")[:500],
                http_status=str(http_status),
                reason=str(result.get("error") or "session invalid")[:200],
            ),
        )
    return JSONResponse(
        status_code=result.get("http_status") or 502,
        content=build_error(
            "UPSTREAM_ERROR",
            detail=str(result.get("error") or "")[:1000],
            http_status=str(result.get("http_status") or "unknown"),
            reason=str(result.get("error") or "upstream failure")[:200],
        ),
    )


def batch_finalize(content: dict[str, Any]) -> JSONResponse:
    """Batch read finalizer.

    Per Twitter API v2 spec partial failures stay 200 (errors array in body).
    But when *every* item failed (no data, only errors) we surface 404 so the
    caller doesn't have to introspect the body to detect a total miss.
    """
    data = content.get("data")
    errors = content.get("errors")
    if errors and not data:
        return JSONResponse(status_code=404, content=content)
    return JSONResponse(status_code=200, content=content)


def stub_501(
    feature: str,
    reason: str,
    suggestion: Optional[str] = None,
    docs: Optional[str] = None,
) -> JSONResponse:
    """Generate 501 Not Implemented response with structured reason."""
    body = build_error("STUB_NOT_IMPLEMENTED", reason=reason)
    body["errors"][0]["feature"] = feature
    if suggestion:
        body["errors"][0]["suggestion"] = suggestion
    if docs:
        body["errors"][0]["docs"] = docs
    return JSONResponse(status_code=501, content=body)
