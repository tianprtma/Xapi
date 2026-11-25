"""Auth helpers: token extraction, session warmup, login flow.

`auth_token` web cookie → ct0 (csrf) + twid (user_id) lewat GET x.com/home.
Session di-cache (SessionStore) supaya tidak round-trip tiap request.
"""

from __future__ import annotations

import contextvars
import inspect
import json
import re
from typing import Any, Optional
from urllib.parse import unquote, urlparse as _urlparse

from curl_cffi.requests import AsyncSession
from fastapi import HTTPException

from session_cache import SessionStore

from .client_pool import ClientPool, pooled_client
from .config import (
    AUTH_TOKEN_PATTERN,
    DEFAULT_HEADERS,
    HOMEPAGE_URL,
    VIEWER_URL,
    VIEWER_FEATURES,
    VIEWER_FIELD_TOGGLES,
    WEB_BEARER,
    gen_ct0,
    headers_for_token,
    profile_for_token,
    proxy_for_token,
    redact_proxy_creds,
)


# ──────────────────────────── Errors ────────────────────────────


class InvalidTokenError(Exception):
    """Raised when auth_token expired/invalid (server tidak set 'twid')."""

    def __init__(self, http_status: int, message: str, jar: dict[str, str], ct0: str):
        self.http_status = http_status
        self.message = message
        self.jar = jar
        self.ct0 = ct0


class WarmNetworkError(Exception):
    """Raised when the warm-up GET x.com/home fails for network reasons.

    Harus dibedakan dari InvalidTokenError: network failure tidak boleh
    meng-invalidate session cache — sifatnya sementara (502), bukan 401.
    """

    def __init__(self, message: str, http_status: int = 502, *, no_retry: bool = False):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.no_retry = no_retry


_LAST_RESOLVE_ME_WARM_ERR: contextvars.ContextVar[Optional[WarmNetworkError]] = contextvars.ContextVar(
    "xapi_last_resolve_me_warm_err", default=None
)


def get_last_resolve_me_warm_error() -> Optional[WarmNetworkError]:
    return _LAST_RESOLVE_ME_WARM_ERR.get()


def clear_last_resolve_me_warm_error() -> None:
    _LAST_RESOLVE_ME_WARM_ERR.set(None)


async def _evict_invalid_token_state(auth_token: str) -> None:
    from .response_cache import ResponseCache
    ResponseCache.get().invalidate_token(auth_token)
    store = SessionStore.get()
    if hasattr(store, "invalidate"):
        inv_s = store.invalidate(auth_token, all_proxies=True)
        if inspect.isawaitable(inv_s):
            await inv_s
    cp = ClientPool.get()
    if hasattr(cp, "invalidate"):
        inv_c = cp.invalidate(auth_token, all_proxies=True)
        if inspect.isawaitable(inv_c):
            await inv_c


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
    """AsyncSession dengan TLS impersonation & Client Hints deterministik per `auth_token`."""
    prof = profile_for_token(auth_token)
    headers = headers_for_token(auth_token)
    proxy = proxy_for_token(auth_token)
    kwargs: dict[str, Any] = dict(
        cookies={"auth_token": auth_token, "ct0": gen_ct0()},
        headers=headers,
        timeout=20.0,
        impersonate=prof["impersonate"],
        allow_redirects=True,
        trust_env=False,
    )
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    import asyncio as _asyncio
    try:
        _asyncio.get_running_loop()
    except RuntimeError:
        try:
            _asyncio.get_event_loop()
        except RuntimeError:
            _asyncio.set_event_loop(_asyncio.new_event_loop())
    return AsyncSession(**kwargs)


def api_headers(ct0: str, auth_token: Optional[str] = None) -> dict[str, str]:
    """Standard headers untuk GraphQL/REST 1.1 calls, sinkron dengan profil `auth_token`."""
    base = headers_for_token(auth_token) if auth_token else DEFAULT_HEADERS
    return {
        **base,
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

    # Cache miss (after invalidation or 20-min expiry): reset any stale cookies
    # (especially old `twid` / `.x.com` `ct0`) on a reused pooled client so a
    # revoked token cannot be re-cached from leftover jar state.
    if hasattr(client.cookies, "jar") and hasattr(client.cookies.jar, "clear"):
        client.cookies.jar.clear()
    client.cookies.set("auth_token", auth_token)
    client.cookies.set("ct0", gen_ct0())

    def _transient_warm_status(resp: Any) -> Optional[int]:
        st = getattr(resp, "status_code", None)
        if isinstance(st, int) and (st >= 500 or st in (408, 429)):
            return 502 if st == 408 else st
        return None

    home_resp: Any = None
    try:
        home_resp = await client.get(HOMEPAGE_URL)
        bad_st = _transient_warm_status(home_resp)
        if bad_st is not None:
            home_resp = await client.get(HOMEPAGE_URL)
            bad_st = _transient_warm_status(home_resp)
            if bad_st is not None:
                if bad_st != 429:
                    await ClientPool.get().invalidate(auth_token, all_proxies=False)
                raise WarmNetworkError(
                    f"GET {HOMEPAGE_URL} returned HTTP {bad_st} twice",
                    http_status=bad_st,
                    no_retry=(bad_st != 429),
                )
    except WarmNetworkError:
        raise
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger("xapi.auth").debug("warm_session home_page failed", exc_info=True)
        # Retry sekali — glitch jaringan/proxy satu-off jangan langsung gagal.
        try:
            home_resp = await client.get(HOMEPAGE_URL)
            bad_st = _transient_warm_status(home_resp)
            if bad_st is not None:
                if bad_st != 429:
                    await ClientPool.get().invalidate(auth_token, all_proxies=False)
                raise WarmNetworkError(
                    f"GET {HOMEPAGE_URL} returned HTTP {bad_st} on retry",
                    http_status=bad_st,
                    no_retry=(bad_st != 429),
                )
        except WarmNetworkError:
            raise
        except Exception as exc:  # noqa: BLE001
            await ClientPool.get().invalidate(auth_token, all_proxies=False)
            raise WarmNetworkError(
                redact_proxy_creds(f"GET {HOMEPAGE_URL} failed twice: {type(exc).__name__}: {exc}"),
                no_retry=True,
            ) from exc

    # Jika proxy/WAF menolak GET /home (mis. 407 Proxy Auth, 402 kuota proxy habis,
    # 403 challenge Cloudflare pada IP proxy), JANGAN salah klasifikasikan ketiadaan
    # cookie `twid` sebagai 401 InvalidTokenError (yang mengkarantina token sehat!).
    final_home_st = getattr(home_resp, "status_code", None)
    if isinstance(final_home_st, int) and final_home_st >= 400 and final_home_st != 401:
        await ClientPool.get().invalidate(auth_token, all_proxies=False)
        mapped_st = 403 if final_home_st == 403 else 502
        raise WarmNetworkError(
            f"GET {HOMEPAGE_URL} rejected by proxy/upstream (HTTP {final_home_st})",
            http_status=mapped_st,
            no_retry=(final_home_st in (402, 407)),
        )

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
        await _evict_invalid_token_state(auth_token)
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


async def login_with_auth_token(auth_token: str, *, _rewarm_retry: bool = False) -> dict[str, Any]:
    """Validate auth_token + fetch viewer profile.

    Fast path: cached viewer dari SessionStore (TTL 5 min) — skip upstream call.

    Returns dict: {status: valid|invalid, http_status, cookies, tokens, user}
    """
    import asyncio as _asyncio

    store = SessionStore.get()
    cached = await store.lookup_viewer(auth_token)
    if cached:
        return cached

    had_cached_session = False
    if not _rewarm_retry:
        _lk = getattr(store, "lookup", None)
        if callable(_lk):
            _cand = _lk(auth_token)
            if _asyncio.iscoroutine(_cand):
                had_cached_session = (await _cand) is not None
    need_rewarm = False

    async with pooled_client(auth_token) as client:
        try:
            ct0, _ = await warm_session(client, auth_token)
        except InvalidTokenError as e:
            await _evict_invalid_token_state(auth_token)
            return {
                "status": "invalid",
                "http_status": e.http_status,
                "error": e.message,
                "cookies": e.jar,
                "tokens": {"bearer": WEB_BEARER, "ct0": e.ct0, "auth_token": auth_token},
                "user": None,
            }
        except WarmNetworkError as e:
            return {
                "status": "error",
                "http_status": getattr(e, "http_status", 502),
                "error": f"warm-up failed: {e.message}",
                "cookies": {},
                "tokens": {"bearer": WEB_BEARER, "ct0": "", "auth_token": auth_token},
                "user": None,
            }

        v_headers = api_headers(ct0, auth_token)
        try:
            from tid_provider import TIDProvider
            tid = await TIDProvider.get().generate("GET", _urlparse(VIEWER_URL).path, auth_token)
            if tid:
                v_headers["x-client-transaction-id"] = tid
        except Exception:  # noqa: BLE001
            pass

        try:
            viewer_resp = await client.get(
                VIEWER_URL,
                headers=v_headers,
                params={
                    "variables": json.dumps({"withCommunitiesMemberships": True}),
                    "features": json.dumps(VIEWER_FEATURES),
                    "fieldToggles": json.dumps(VIEWER_FIELD_TOGGLES),
                },
            )
        except Exception as exc:  # noqa: BLE001
            await ClientPool.get().invalidate(auth_token, all_proxies=False)
            return {
                "status": "error",
                "http_status": 502,
                "error": redact_proxy_creds(f"viewer request failed: {type(exc).__name__}: {exc}"),
                "cookies": {},
                "tokens": {"bearer": WEB_BEARER, "ct0": ct0, "auth_token": auth_token},
                "user": None,
            }

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
        elif viewer_resp.status_code == 401:
            from .response_cache import ResponseCache
            ResponseCache.get().invalidate_token(auth_token)
            if hasattr(store, "invalidate"):
                await store.invalidate(auth_token, all_proxies=True)
            await ClientPool.get().invalidate(auth_token, all_proxies=True)
            if had_cached_session:
                need_rewarm = True
            else:
                return {
                    "status": "invalid",
                    "http_status": 401,
                    "error": viewer_resp.text[:500],
                    "cookies": jar,
                    "tokens": {"bearer": WEB_BEARER, "ct0": ct0, "auth_token": auth_token},
                    "user": None,
                }
        else:
            raw_v_st = viewer_resp.status_code
            if raw_v_st == 403:
                if hasattr(store, "invalidate"):
                    await store.invalidate(auth_token, all_proxies=False)
                await ClientPool.get().invalidate(auth_token, all_proxies=False)
                if had_cached_session:
                    need_rewarm = True
                err_st = 403
            elif raw_v_st in (402, 407):
                await ClientPool.get().invalidate(auth_token, all_proxies=False)
                err_st = 502
            else:
                err_st = raw_v_st if raw_v_st >= 400 else 502
            if not need_rewarm:
                return {
                    "status": "error",
                    "http_status": err_st,
                    "error": viewer_resp.text[:500],
                    "cookies": jar,
                    "tokens": {"bearer": WEB_BEARER, "ct0": ct0, "auth_token": auth_token},
                    "user": None,
                }

        if not need_rewarm:
            result = {
                "status": "valid",
                "http_status": 200,
                "cookies": jar,
                "tokens": {"bearer": WEB_BEARER, "ct0": ct0, "auth_token": auth_token},
                "user": user_data,
            }
            await store.store_viewer(auth_token, result)
            return result

    return await login_with_auth_token(auth_token, _rewarm_retry=True)


async def resolve_me_id(auth_token: str) -> Optional[str]:
    """Resolve current user_id dari cookie twid (no Viewer call)."""
    _LAST_RESOLVE_ME_WARM_ERR.set(None)
    async with pooled_client(auth_token) as client:
        try:
            await warm_session(client, auth_token)
        except InvalidTokenError:
            await _evict_invalid_token_state(auth_token)
            return None
        except WarmNetworkError as e:
            _LAST_RESOLVE_ME_WARM_ERR.set(e)
            return None
        jar = {c.name: c.value for c in client.cookies.jar}
        return extract_user_id_from_twid(jar.get("twid"))
