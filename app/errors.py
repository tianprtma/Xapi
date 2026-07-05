"""Structured error catalog — unique error codes per failure class.

Every error response includes a machine-readable `code` so callers can
branch on error class without parsing prose detail strings.

Format: ERR_{domain}_{specific}
  - AUTH_*     — authentication / authorization
  - UPSTREAM_* — X upstream failures
  - VALIDATION_* — input validation
  - RATE_*     — rate limiting
  - INFRA_*    — internal / infrastructure
  - MEDIA_*    — media upload
  - XCHAT_*    — XChat bridge
  - STUB_*     — unimplemented endpoints
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional


@dataclasses.dataclass(frozen=True)
class ErrorCode:
    code: str          # machine-readable: "AUTH_TOKEN_MISSING"
    title: str         # short human label: "Authentication Required"
    http_status: int   # recommend HTTP status
    detail_template: str  # format string, e.g. "No auth_token in {location}"
    legacy_type: Optional[str] = None  # preserve old format_error(type_=...) values


# ──────────────────────────── Auth (AUTH_) ────────────────────────────

ERROR_CODES: dict[str, ErrorCode] = {
    # Token missing / malformed
    "AUTH_TOKEN_MISSING": ErrorCode(
        code="AUTH_TOKEN_MISSING",
        title="Authentication Required",
        http_status=401,
        detail_template="missing auth_token (provide 'Authorization: Bearer <auth_token>' header)",
        legacy_type="unauthorized",
    ),
    "AUTH_TOKEN_INVALID_FORMAT": ErrorCode(
        code="AUTH_TOKEN_INVALID_FORMAT",
        title="Invalid Token Format",
        http_status=401,
        detail_template="auth_token must be 40 hex characters",
        legacy_type="unauthorized",
    ),
    "AUTH_TOKEN_EXPIRED": ErrorCode(
        code="AUTH_TOKEN_EXPIRED",
        title="Token Expired",
        http_status=401,
        detail_template="auth_token expired or invalid (X did not set 'twid' cookie)",
        legacy_type="unauthorized",
    ),
    "AUTH_QUERY_DISABLED": ErrorCode(
        code="AUTH_QUERY_DISABLED",
        title="Query Auth Disabled",
        http_status=401,
        detail_template="query-string auth disabled in this environment (use Authorization header)",
        legacy_type="unauthorized",
    ),
    "AUTH_ADMIN_REQUIRED": ErrorCode(
        code="AUTH_ADMIN_REQUIRED",
        title="Admin Access Required",
        http_status=401,
        detail_template="valid X-Admin-Token header required",
        legacy_type="unauthorized",
    ),

    # ──────────────────────── Upstream (UPSTREAM_) ────────────────────────

    "UPSTREAM_ERROR": ErrorCode(
        code="UPSTREAM_ERROR",
        title="Upstream Error",
        http_status=502,
        detail_template="X upstream returned {http_status}: {reason}",
    ),
    "UPSTREAM_TIMEOUT": ErrorCode(
        code="UPSTREAM_TIMEOUT",
        title="Upstream Timeout",
        http_status=504,
        detail_template="X upstream timed out after {timeout}s",
    ),
    "UPSTREAM_NON_JSON": ErrorCode(
        code="UPSTREAM_NON_JSON",
        title="Upstream Parse Error",
        http_status=502,
        detail_template="X returned non-JSON response",
    ),
    "UPSTREAM_RETRY_EXHAUSTED": ErrorCode(
        code="UPSTREAM_RETRY_EXHAUSTED",
        title="Upstream Unavailable",
        http_status=502,
        detail_template="X upstream still failing after {attempts} attempts (last: HTTP {last_status})",
    ),
    "UPSTREAM_AUTH_REJECTED": ErrorCode(
        code="UPSTREAM_AUTH_REJECTED",
        title="Upstream Auth Rejected",
        http_status=401,
        detail_template="X rejected this session — token may have been revoked",
    ),

    # ──────────────────────── Validation (VALIDATION_) ────────────────────────

    "VALIDATION_BODY_SIZE": ErrorCode(
        code="VALIDATION_BODY_SIZE",
        title="Payload Too Large",
        http_status=413,
        detail_template="request body exceeds {max_bytes} bytes",
        legacy_type="payload_too_large",
    ),
    "VALIDATION_MISSING_PARAM": ErrorCode(
        code="VALIDATION_MISSING_PARAM",
        title="Missing Parameter",
        http_status=400,
        detail_template="required parameter '{param}' is missing",
    ),
    "VALIDATION_INVALID_PARAM": ErrorCode(
        code="VALIDATION_INVALID_PARAM",
        title="Invalid Parameter",
        http_status=400,
        detail_template="parameter '{param}' is invalid: {reason}",
    ),
    "VALIDATION_MEDIA_SIZE": ErrorCode(
        code="VALIDATION_MEDIA_SIZE",
        title="Media Too Large",
        http_status=413,
        detail_template="media upload exceeds {max_bytes} bytes",
    ),

    # ──────────────────────── Rate Limit (RATE_) ────────────────────────

    "RATE_LIMIT_EXCEEDED": ErrorCode(
        code="RATE_LIMIT_EXCEEDED",
        title="Rate Limit Exceeded",
        http_status=429,
        detail_template="rate limit exceeded — retry after {retry_after}s",
    ),

    # ──────────────────────── Infra (INFRA_) ────────────────────────

    "INFRA_UNKNOWN_OPERATION": ErrorCode(
        code="INFRA_UNKNOWN_OPERATION",
        title="Unknown GraphQL Operation",
        http_status=500,
        detail_template="unknown GraphQL operation: {operation}",
    ),
    "INFRA_INTERNAL_ERROR": ErrorCode(
        code="INFRA_INTERNAL_ERROR",
        title="Internal Server Error",
        http_status=500,
        detail_template="internal server error",
    ),
    "INFRA_SERVICE_UNAVAILABLE": ErrorCode(
        code="INFRA_SERVICE_UNAVAILABLE",
        title="Service Unavailable",
        http_status=503,
        detail_template="service temporarily unavailable: {reason}",
    ),
    "INFRA_NOT_FOUND": ErrorCode(
        code="INFRA_NOT_FOUND",
        title="Not Found",
        http_status=404,
        detail_template="no API route matches {method} {path}",
    ),
    "INFRA_RAW_DISABLED": ErrorCode(
        code="INFRA_RAW_DISABLED",
        title="Raw Mode Disabled",
        http_status=403,
        detail_template="raw mode disabled in this environment",
        legacy_type="forbidden",
    ),

    # ──────────────────────── Media (MEDIA_) ────────────────────────

    "MEDIA_INIT_FAILED": ErrorCode(
        code="MEDIA_INIT_FAILED",
        title="Media Init Failed",
        http_status=502,
        detail_template="media INIT failed: {error}",
    ),
    "MEDIA_APPEND_FAILED": ErrorCode(
        code="MEDIA_APPEND_FAILED",
        title="Media Append Failed",
        http_status=502,
        detail_template="media APPEND segment {segment} failed: {error}",
    ),
    "MEDIA_FINALIZE_FAILED": ErrorCode(
        code="MEDIA_FINALIZE_FAILED",
        title="Media Finalize Failed",
        http_status=502,
        detail_template="media FINALIZE failed: {error}",
    ),
    "MEDIA_PROCESSING_FAILED": ErrorCode(
        code="MEDIA_PROCESSING_FAILED",
        title="Media Processing Failed",
        http_status=502,
        detail_template="media processing failed: {error}",
    ),

    # ──────────────────────── XChat (XCHAT_) ────────────────────────

    "XCHAT_BRIDGE_UNAVAILABLE": ErrorCode(
        code="XCHAT_BRIDGE_UNAVAILABLE",
        title="XChat Bridge Unavailable",
        http_status=503,
        detail_template="XChat bridge not ready — chat.db may not be synced yet",
    ),
    "XCHAT_BRIDGE_AUTH_REJECTED": ErrorCode(
        code="XCHAT_BRIDGE_AUTH_REJECTED",
        title="XChat Bridge Auth Rejected",
        http_status=401,
        detail_template="XChat bridge: auth_token invalid (X redirected to login)",
    ),
    "XCHAT_BRIDGE_MAX_REBUILDS": ErrorCode(
        code="XCHAT_BRIDGE_MAX_REBUILDS",
        title="XChat Bridge Failed",
        http_status=503,
        detail_template="XChat bridge exceeded max rebuilds — profile may be corrupt",
    ),

    # ──────────────────────── Stubs (STUB_) ────────────────────────

    "STUB_NOT_IMPLEMENTED": ErrorCode(
        code="STUB_NOT_IMPLEMENTED",
        title="Not Implemented",
        http_status=501,
        detail_template="{reason}",
        legacy_type="not_implemented",
    ),
    "STUB_OAUTH2_REQUIRED": ErrorCode(
        code="STUB_OAUTH2_REQUIRED",
        title="OAuth2 Required",
        http_status=501,
        detail_template="endpoint requires OAuth2 user-context with scopes — cookie mode unavailable",
    ),
    "STUB_NEW_GQL_REQUIRED": ErrorCode(
        code="STUB_NEW_GQL_REQUIRED",
        title="Undiscovered GraphQL Operation",
        http_status=501,
        detail_template="operation requires undiscovered GraphQL query — add to _gql_meta.json",
    ),
}


def build_error(
    error_key: str,
    *,
    detail: Optional[str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a v2-style error response dict from an error code key.

    Example:
        build_error("AUTH_TOKEN_MISSING")
        → {"errors": [{"code": "AUTH_TOKEN_MISSING", "title": "...", ...}]}

    Extra kwargs are interpolated into the detail_template.
    """
    ec = ERROR_CODES.get(error_key)
    if ec is None:
        ec = ERROR_CODES["INFRA_INTERNAL_ERROR"]
        kwargs = {"reason": f"unknown error code: {error_key}"}

    detail_text = detail or ec.detail_template.format(**kwargs)
    return {
        "errors": [
            {
                "code": ec.code,
                "title": ec.title,
                "detail": detail_text,
                "type": ec.legacy_type or ec.code.lower(),
                "status": ec.http_status,
            }
        ]
    }


def build_error_jsonapi(
    error_key: str,
    *,
    detail: Optional[str] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Legacy JSON:API-style error (no {errors: [...]} wrapper).

    Used where existing response format requires flat error shape.
    """
    ec = ERROR_CODES.get(error_key)
    if ec is None:
        ec = ERROR_CODES["INFRA_INTERNAL_ERROR"]
        kwargs = {"reason": f"unknown error code: {error_key}"}
    detail_text = detail or ec.detail_template.format(**kwargs)
    return {
        "errors": [
            {
                "title": ec.title,
                "detail": detail_text,
                "type": ec.legacy_type or ec.code.lower(),
                "status": ec.http_status,
                "code": ec.code,
            }
        ]
    }
