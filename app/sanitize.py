"""Input sanitization for user-provided query parameters and path segments.

X api responds with 400 for obviously malicious inputs rather than
forwarding them upstream. This is defense-in-depth — the upstream
GraphQL layer has its own guards, but we can reject garbage earlier
and with clearer error messages.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Optional


# Max username length on X is 15 chars. Allow up to 30 for safety margin.
MAX_USERNAME_LEN = 30
# Tweet IDs are 64-bit ints (~19 digits).
MAX_ID_LEN = 30
# Search query max reasonable length.
MAX_QUERY_LEN = 500

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,30}$")
TWEET_ID_RE = re.compile(r"^[0-9]{1,30}$")


def sanitize_username(value: Optional[str]) -> Optional[str]:
    """Validate and return a sanitized username. Returns None if invalid."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_USERNAME_LEN:
        return None
    if not USERNAME_RE.match(value):
        return None
    return value


def sanitize_tweet_id(value: Optional[str]) -> Optional[str]:
    """Validate and return a sanitized tweet/user ID. Returns None if invalid."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_ID_LEN:
        return None
    if not TWEET_ID_RE.match(value):
        return None
    return value


def sanitize_csv_ids(value: Optional[str]) -> list[str]:
    """Parse and validate comma-separated ID list. Returns list of valid IDs."""
    if value is None:
        return []
    ids = [v.strip() for v in value.split(",") if v.strip()]
    return [i for i in ids if TWEET_ID_RE.match(i) and len(i) <= MAX_ID_LEN]


def sanitize_search_query(value: Optional[str]) -> str:
    """Sanitize search query — trim + length limit. Returns empty str if invalid."""
    if value is None:
        return ""
    value = value.strip()
    if len(value) > MAX_QUERY_LEN:
        return value[:MAX_QUERY_LEN]
    return value


def sanitize_url_param(value: Optional[str], *, decode: bool = True) -> Optional[str]:
    """URL-decode (optional) and sanitize a path/query parameter.

    Strips null bytes, control characters, and length-limited.
    Returns None if input is empty after sanitization.
    """
    if value is None:
        return None
    if decode:
        try:
            decoded = urllib.parse.unquote(value, errors="strict")
        except (ValueError, UnicodeDecodeError):
            return None
    else:
        decoded = value
    # Strip null bytes + control chars (except whitespace)
    cleaned = decoded.replace("\x00", "")
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    if len(cleaned) > 500:
        return cleaned[:500]
    return cleaned


# ──────────────────────────── Query-param sanitizer middleware ────────────────────────────


# Paths under /2/ that carry user-controlled identifiers — skip sanitization
# for params with known strict pydantic regex patterns (^\d+$, ^[a-zA-Z0-9_]+$).
# We only sanitize free-text params: q, query, screen_name, cursor, etc.
_SANITIZE_PARAM_NAMES = frozenset({
    "q", "query", "screen_name", "cursor", "display_name",
    "description", "name", "text", "bio", "location", "url",
})

from starlette.types import ASGIApp, Scope, Receive, Send, Message


class QueryParamSanitizerMiddleware:
    """ASGI middleware: strip null bytes and control chars from free-text query params.

    Rejects with 400 if any sanitized param becomes empty (originally non-empty but
    all control chars — likely probe/attack).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_qs = scope.get("query_string", b"")
        if not raw_qs:
            await self.app(scope, receive, send)
            return

        try:
            qs = raw_qs.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError):
            # Invalid UTF-8 in query string — likely probe/attack
            import json as _json
            from app.errors import build_error as _build_error
            body = _json.dumps(_build_error("VALIDATION_INVALID_PARAM", param="query", reason="invalid utf-8")).encode()
            await send({
                "type": "http.response.start",
                "status": 400,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({"type": "http.response.body", "body": body, "more_body": False})
            return

        parsed = urllib.parse.parse_qs(qs, keep_blank_values=True)
        mutated = False
        for name in list(parsed.keys()):
            if name not in _SANITIZE_PARAM_NAMES:
                continue
            values = parsed[name]
            cleaned = []
            for v in values:
                # parse_qs already URL-decoded `v` — do NOT double-unquote it,
                # otherwise valid literals like `%2520`, `%25ff`, `%252B` get
                # corrupted or dropped.
                sv = sanitize_url_param(v, decode=False)
                if sv is not None:
                    if sv != v:
                        mutated = True
                    cleaned.append(sv)
                elif v != "":
                    # Originally non-empty value reduced to empty (all control chars/whitespace)
                    import json as _json
                    from app.errors import build_error as _build_error
                    body = _json.dumps(_build_error("VALIDATION_INVALID_PARAM", param=name, reason="empty after sanitization")).encode()
                    await send({
                        "type": "http.response.start",
                        "status": 400,
                        "headers": [(b"content-type", b"application/json")],
                    })
                    await send({"type": "http.response.body", "body": body, "more_body": False})
                    return
                else:
                    mutated = True  # originally empty value → drop this occurrence
            if cleaned:
                parsed[name] = cleaned
            else:
                del parsed[name]
                mutated = True

        if not mutated:
            await self.app(scope, receive, send)
            return

        # Rebuild query string
        new_qs = urllib.parse.urlencode(parsed, doseq=True)
        scope["query_string"] = new_qs.encode("utf-8")
        await self.app(scope, receive, send)
