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

from formatter import format_error


# ──────────────────────────── Wrappers ────────────────────────────


def wrap(result: dict[str, Any]) -> JSONResponse:
    """Pass-through: HTTP code by status, body = raw result dict."""
    code_map = {"ok": 200, "valid": 200, "invalid": 401, "error": 502}
    return JSONResponse(status_code=code_map.get(result["status"], 500), content=result)


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

    if result["status"] in ("ok", "valid"):
        formatted = formatter(result.get("data") or {})
        # Error sintaks dari GraphQL (formatter detect schema mismatch)?
        if "errors" in formatted and not formatted.get("data"):
            return JSONResponse(status_code=404, content=formatted)
        return JSONResponse(status_code=200, content=formatted)

    if result["status"] == "invalid":
        return JSONResponse(
            status_code=401,
            content=format_error(
                "Unauthorized",
                detail=result.get("error") or "auth_token invalid/expired",
                type_="unauthorized",
                status=401,
            ),
        )

    return JSONResponse(
        status_code=502,
        content=format_error(
            "Upstream Error",
            detail=str(result.get("error") or "GraphQL call failed")[:500],
            type_="upstream_error",
            status=result.get("http_status") or 502,
        ),
    )


def write_finalize(result: dict[str, Any], raw: bool) -> JSONResponse:
    """Write endpoint finalizer: balikin {data: <gql payload>} atau errors."""
    if raw:
        return wrap(result)
    if result["status"] == "ok":
        return JSONResponse(status_code=200, content={"data": result.get("data")})
    if result["status"] == "invalid":
        return JSONResponse(
            status_code=401,
            content=format_error(
                "Unauthorized",
                str(result.get("error") or "")[:500],
                "unauthorized",
                401,
            ),
        )
    return JSONResponse(
        status_code=result.get("http_status") or 502,
        content=format_error(
            "Upstream Error",
            str(result.get("error") or "")[:1000],
            "upstream_error",
            result.get("http_status") or 502,
        ),
    )


def stub_501(
    feature: str,
    reason: str,
    suggestion: Optional[str] = None,
    docs: Optional[str] = None,
) -> JSONResponse:
    """Generate 501 Not Implemented response with structured reason."""
    body: dict[str, Any] = {
        "errors": [
            {
                "title": "Not Implemented",
                "detail": reason,
                "type": "not_implemented",
                "status": 501,
                "feature": feature,
            }
        ]
    }
    if suggestion:
        body["errors"][0]["suggestion"] = suggestion
    if docs:
        body["errors"][0]["docs"] = docs
    return JSONResponse(status_code=501, content=body)
