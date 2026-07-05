"""Auth helpers: token extraction, session warmup, login flow.

`auth_token` web cookie → ct0 (csrf) + twid (user_id) lewat GET x.com/home.
Session di-cache (SessionStore) supaya tidak round-trip tiap request.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import unquote, urlparse as _urlparse

from curl_cffi.requests import AsyncSession
from fastapi import HTTPException

from session_cache import SessionStore

from .client_pool import pooled_client
from .config import (
    AUTH_TOKEN_PATTERN,
    DEFAULT_HEADERS,
    HOMEPAGE_URL,
    VIEWER_URL,
    VIEWER_FEATURES,
    VIEWER_FIELD_TOGGLES,
    WEB_BEARER,
    gen_ct0,
    random_proxy,
    random_user_agent,
)


# ──────────────────────────── Errors ────────────────────────────


class InvalidTokenError(Exception):
    """Raised when auth_token expired/invalid (server tidak set 'twid')."""

    def __init__(self, http_status: int, message: str, jar: dict[str, str], ct0: str):
        self.http_status = http_status
        self.message = message
        self.jar = jar
        self.ct0 = ct0


# ──────────────────────────── Helpers ────────────────────────────


def extract_user_id_from_twid(twid: str | None) -> str | None:
    """Parse user_id dari cookie `twid` (format: u%3D<id>)."""
    if not twid:
        return None
    m = re.search(r"u=(\d+)", unquote(twid))
    return m.group(1) if m else None


def extract_bearer(authorization: Optional[str], auth_token_q: Optional[str]) -> str:
    """Resolve auth_token dari header `Authorization: Bearer xxx`.

    Query `?auth_token=` masih diterima sebagai fallback (backwards-compat),
    TAPI di prod sebaiknya direject — env `ALLOW_QUERY_AUTH=0` melarang query auth.
    Token query bocor di access log reverse proxy/CDN/browser history.

    Validates format `^[a-f0-9]{40}$` — invalid format = 401 sebelum upstream call.
    """
    from .config import ALLOW_QUERY_AUTH

    tok: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization.split(" ", 1)[1].strip()
        if candidate:
            tok = candidate
    if not tok and auth_token_q:
        if not ALLOW_QUERY_AUTH:
            raise HTTPException(
                status_code=401,
                detail=(
                    "query-string auth disabled in this environment "
                    "(use 'Authorization: Bearer <auth_token>' header)"
                ),
            )
        tok = auth_token_q.strip()

    if not tok:
        from .errors import build_error_jsonapi
        raise HTTPException(
            status_code=401,
            detail=build_error_jsonapi("AUTH_TOKEN_MISSING")["errors"][0]["detail"],
        )

    if not AUTH_TOKEN_PATTERN.match(tok):
        from .errors import build_error_jsonapi
        raise HTTPException(
            status_code=401,
            detail=build_error_jsonapi("AUTH_TOKEN_INVALID_FORMAT")["errors"][0]["detail"],
        )
    return tok


def make_client(auth_token: str) -> AsyncSession:
    """AsyncSession dengan TLS impersonation Chrome 124 (lolos JA3 fingerprint check X).

    Per-request: random UA dari pool + random proxy dari PROXY_LIST (kalau set).
    """
    headers = {**DEFAULT_HEADERS, "user-agent": random_user_agent()}
    proxy = random_proxy()
    kwargs: dict[str, Any] = dict(
        cookies={"auth_token": auth_token, "ct0": gen_ct0()},
        headers=headers,
        timeout=20.0,
        impersonate="chrome124",
        allow_redirects=True,
    )
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    return AsyncSession(**kwargs)


def api_headers(ct0: str) -> dict[str, str]:
    """Standard headers untuk GraphQL/REST 1.1 calls."""
    return {
        **DEFAULT_HEADERS,
        "authorization": f"Bearer {WEB_BEARER}",
        "x-csrf-token": ct0,
        "content-type": "application/json",
    }


# ──────────────────────────── Session warmup ────────────────────────────


async def warm_session(
    client: AsyncSession, auth_token: str
) -> tuple[str, dict[str, str]]:
    """Cek cache → kalau tidak ada, GET x.com/home untuk dapat ct0 + twid.

    Returns:
        (ct0, full_cookie_jar)

    Raises:
        InvalidTokenError: kalau twid tidak di-set (auth_token expired/invalid).
    """
    store = SessionStore.get()
    cached = await store.lookup(auth_token)
    if cached:
        client.cookies.jar.clear()
        for k, v in cached.cookies.items():
            client.cookies.set(k, v, domain=".x.com")
        return cached.ct0, cached.cookies

    try:
        await client.get(HOMEPAGE_URL)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("xapi.auth").debug("warm_session home_page failed", exc_info=True)

    # X kasih ct0 server-issued di domain .x.com (leading dot). Placeholder lokal
    # nyantol di domain="" atau "x.com" tanpa leading dot. Strategy: prefer ct0
    # dari .x.com, kalau ada → drop semua ct0 lain.
    server_ct0_value: Optional[str] = None
    for ck in list(client.cookies.jar):
        if ck.name == "ct0" and (ck.domain or "").startswith("."):
            server_ct0_value = ck.value
            break

    if server_ct0_value:
        keep = [
            ck for ck in client.cookies.jar
            if not (ck.name == "ct0" and not (ck.domain or "").startswith("."))
        ]
        client.cookies.jar.clear()
        for ck in keep:
            client.cookies.jar.set_cookie(ck)

    jar = {c.name: c.value for c in client.cookies.jar}
    ct0 = server_ct0_value or jar.get("ct0", "")

    if not jar.get("twid"):
        raise InvalidTokenError(
            http_status=401,
            message="auth_token expired atau tidak valid (server tidak set cookie 'twid')",
            jar=jar,
            ct0=ct0,
        )

    user_id = extract_user_id_from_twid(jar.get("twid"))
    await store.store(auth_token, ct0, jar, user_id=user_id)
    return ct0, jar


# ──────────────────────────── Login flow ────────────────────────────


async def login_with_auth_token(auth_token: str) -> dict[str, Any]:
    """Validate auth_token + fetch viewer profile.

    Fast path: cached viewer dari SessionStore (TTL 5 min) — skip upstream call.

    Returns dict: {status: valid|invalid, http_status, cookies, tokens, user}
    """
    store = SessionStore.get()
    cached = await store.lookup_viewer(auth_token)
    if cached:
        return cached

    async with pooled_client(auth_token) as client:
        try:
            ct0, _ = await warm_session(client, auth_token)
        except InvalidTokenError as e:
            return {
                "status": "invalid",
                "http_status": e.http_status,
                "error": e.message,
                "cookies": e.jar,
                "tokens": {"bearer": WEB_BEARER, "ct0": e.ct0, "auth_token": auth_token},
                "user": None,
            }

        viewer_resp = await client.get(
            VIEWER_URL,
            headers=api_headers(ct0),
            params={
                "variables": json.dumps({"withCommunitiesMemberships": True}),
                "features": json.dumps(VIEWER_FEATURES),
                "fieldToggles": json.dumps(VIEWER_FIELD_TOGGLES),
            },
        )

        jar = {c.name: c.value for c in client.cookies.jar}
        ct0 = jar.get("ct0", ct0)

        user_data: dict[str, Any] = {
            "id": extract_user_id_from_twid(jar.get("twid")),
            "screen_name": None,
            "name": None,
            "followers_count": None,
            "friends_count": None,
            "statuses_count": None,
            "verified": None,
            "protected": None,
            "created_at": None,
            "email": None,
            "lang": None,
        }

        if viewer_resp.status_code == 200:
            try:
                v = viewer_resp.json()
                user_result = (
                    v.get("data", {})
                    .get("viewer", {})
                    .get("user_results", {})
                    .get("result", {})
                )
                legacy = user_result.get("legacy", {}) or {}
                core = user_result.get("core", {}) or {}
                user_data.update({
                    "id": user_result.get("rest_id") or user_data["id"],
                    "screen_name": core.get("screen_name") or legacy.get("screen_name"),
                    "name": core.get("name") or legacy.get("name"),
                    "followers_count": legacy.get("followers_count"),
                    "friends_count": legacy.get("friends_count"),
                    "statuses_count": legacy.get("statuses_count"),
                    "verified": user_result.get("is_blue_verified") or legacy.get("verified"),
                    "protected": legacy.get("protected"),
                    "created_at": core.get("created_at") or legacy.get("created_at"),
                })
            except (json.JSONDecodeError, KeyError, AttributeError):
                pass
        elif viewer_resp.status_code in (401, 403):
            return {
                "status": "invalid",
                "http_status": viewer_resp.status_code,
                "error": viewer_resp.text[:500],
                "cookies": jar,
                "tokens": {"bearer": WEB_BEARER, "ct0": ct0, "auth_token": auth_token},
                "user": None,
            }

        result = {
            "status": "valid",
            "http_status": 200,
            "cookies": jar,
            "tokens": {"bearer": WEB_BEARER, "ct0": ct0, "auth_token": auth_token},
            "user": user_data,
        }
        await store.store_viewer(auth_token, result)
        return result


async def resolve_me_id(auth_token: str) -> Optional[str]:
    """Resolve current user_id dari cookie twid (no Viewer call)."""
    async with pooled_client(auth_token) as client:
        try:
            await warm_session(client, auth_token)
        except InvalidTokenError:
            return None
        jar = {c.name: c.value for c in client.cookies.jar}
        return extract_user_id_from_twid(jar.get("twid"))
