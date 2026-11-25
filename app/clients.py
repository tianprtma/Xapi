"""HTTP clients: GraphQL, REST 1.1, DM, media upload.

Semua function balikin shape standar:
    {status: ok|invalid|error, http_status, data?, error?, cookies, tokens}
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from typing import Any, Optional
from urllib.parse import urlparse as _urlparse

from fastapi import HTTPException

from curl_cffi import CurlMime
from curl_cffi.requests import AsyncSession as CurlAsyncSession

from session_cache import SessionStore
from tid_provider import TIDProvider

from .auth import (
    InvalidTokenError,
    WarmNetworkError,
    api_headers,
    make_client,
    warm_session,
)
from .client_pool import ClientPool, pooled_client
from .config import (
    CHUNK_SIZE,
    MEDIA_PROXY_EXEMPT,
    DEFAULT_HEADERS,
    DM_BASE,
    DM_DEFAULT_PARAMS,
    GQL_META,
    GRAPHQL_BASE,
    REST_BASE,
    UPLOAD_BASE,
    WEB_BEARER,
    _DIRECT_PROXY_SENTINEL,
    gen_ct0,
    headers_for_token,
    profile_for_token,
    proxy_for_token,
    random_user_agent,
    redact_proxy_creds,
    reset_request_proxy,
    set_request_proxy,
)
from .response_cache import ResponseCache
from .retry import with_retry


# ──────────────────────────── GraphQL ────────────────────────────


# Batasi fan-out paralel ke upstream per request — 100 gather sekaligus
# membuat burst yang memicu rate limit / hang.
FANOUT_SEM_SIZE = 10

import asyncio as _asyncio

def fanout_semaphore() -> _asyncio.Semaphore:
    """Semaphore lazy per event-loop (dibuat sekali)."""
    global _fanout_sem
    try:
        return _fanout_sem
    except NameError:
        _fanout_sem = _asyncio.Semaphore(FANOUT_SEM_SIZE)
        return _fanout_sem



async def graphql_call(
    operation: str,
    variables: dict[str, Any],
    auth_token: str,
    method: str = "GET",
) -> dict[str, Any]:
    """Generic GraphQL caller dengan retry + cache.

    Lookup queryId/features/fieldToggles dari `GQL_META[operation]`. Add
    x-client-transaction-id header (anti-bot) lewat TIDProvider. Read-only
    operations (lihat `response_cache.CACHEABLE_OPS`) di-cache via
    `ResponseCache` selama `RESPONSE_CACHE_TTL` detik.
    """
    cache = ResponseCache.get()
    cached = await cache.lookup(operation, variables, auth_token)
    if cached is not None:
        return {**cached, "cache_hit": True}

    result = await with_retry(_graphql_call_once, operation, variables, auth_token, method)
    await cache.store(operation, variables, auth_token, result)
    return result


# Read-only GraphQL queries yang memakai method="POST" (idempoten, aman untuk 1x
# auto-rewarm saat proxy berotasi mengganti IP sehingga cookie __cf_bm basi).
_IDEMPOTENT_POST_GQL_OPS = frozenset({"SearchTimeline"})


async def _graphql_call_once(
    operation: str,
    variables: dict[str, Any],
    auth_token: str,
    method: str = "GET",
    *,
    _rewarm_retry: bool = False,
) -> dict[str, Any]:
    """Single GraphQL request — no retry, no cache (used by `graphql_call`)."""
    meta = GQL_META.get(operation)
    if not meta:
        raise HTTPException(status_code=500, detail=f"unknown GraphQL op: {operation}")

    url = f"{GRAPHQL_BASE}/{meta['queryId']}/{operation}"
    had_cached_session = False
    if (method == "GET" or operation in _IDEMPOTENT_POST_GQL_OPS) and not _rewarm_retry:
        _lk = getattr(SessionStore.get(), "lookup", None)
        if callable(_lk):
            _cand = _lk(auth_token)
            if asyncio.iscoroutine(_cand):
                had_cached_session = (await _cand) is not None
    need_rewarm = False

    async with pooled_client(auth_token) as client:
        try:
            ct0, _ = await warm_session(client, auth_token)
        except InvalidTokenError as e:
            return _invalid_token_response(e, auth_token)
        except WarmNetworkError as e:
            res_w: dict[str, Any] = {
                "status": "error",
                "http_status": getattr(e, "http_status", 502),
                "error": f"warm-up failed: {e.message}",
                "data": None,
            }
            if getattr(e, "no_retry", False):
                res_w["_no_retry"] = True
            return res_w

        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(meta.get("features", {})),
        }
        if meta.get("fieldToggles"):
            params["fieldToggles"] = json.dumps(meta["fieldToggles"])

        headers = api_headers(ct0, auth_token)
        try:
            tid = await TIDProvider.get().generate(method, _urlparse(url).path, auth_token)
            if tid:
                headers["x-client-transaction-id"] = tid
        except Exception:  # noqa: BLE001
            pass

        try:
            if method == "GET":
                resp = await client.get(url, headers=headers, params=params)
            else:
                resp = await client.post(url, headers=headers, json={
                    "variables": variables,
                    "features": meta.get("features", {}),
                    "fieldToggles": meta.get("fieldToggles", {}),
                    "queryId": meta["queryId"],
                })
        except Exception as exc:  # noqa: BLE001
            await ClientPool.get().invalidate(auth_token, all_proxies=False)
            return {
                "status": "error",
                "http_status": 502,
                "error": redact_proxy_creds(f"upstream request failed: {type(exc).__name__}: {exc}"),
                "data": None,
            }

        if resp.status_code != 200:
            is_proxy_auth_or_quota = resp.status_code in (402, 407)
            if resp.status_code in (401, 403):
                all_p = resp.status_code == 401
                if all_p:
                    ResponseCache.get().invalidate_token(auth_token)
                await SessionStore.get().invalidate(auth_token, all_proxies=all_p)
                await ClientPool.get().invalidate(auth_token, all_proxies=all_p)
                if had_cached_session:
                    need_rewarm = True
            elif is_proxy_auth_or_quota:
                await ClientPool.get().invalidate(auth_token, all_proxies=False)
            if not need_rewarm:
                out_st = 502 if is_proxy_auth_or_quota or resp.status_code < 400 else resp.status_code
                err_out: dict[str, Any] = {
                    "status": "error",
                    "http_status": out_st,
                    "error": redact_proxy_creds(resp.text[:1000]),
                    "data": None,
                }
                if is_proxy_auth_or_quota:
                    err_out["_no_retry"] = True
                return err_out

        if not need_rewarm:
            try:
                payload = resp.json()
            except json.JSONDecodeError:
                return {
                    "status": "error",
                    "http_status": 502,
                    "error": "non-JSON response",
                    "raw": redact_proxy_creds(resp.text[:1000]),
                    "data": None,
                }

            return {
                "status": "ok",
                "http_status": 200,
                "operation": operation,
                "data": payload,
            }

    return await _graphql_call_once(
        operation, variables, auth_token, method, _rewarm_retry=True
    )


# ──────────────────────────── REST 1.1 ────────────────────────────


async def rest_call(
    path: str,
    auth_token: str,
    *,
    method: str = "POST",
    data: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    base: str = REST_BASE,
) -> dict[str, Any]:
    """Generic REST 1.1 caller dengan retry pada transient errors."""
    return await with_retry(
        _rest_call_once,
        path,
        auth_token,
        method=method,
        data=data,
        json_body=json_body,
        base=base,
    )


async def _rest_call_once(
    path: str,
    auth_token: str,
    *,
    method: str = "POST",
    data: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    base: str = REST_BASE,
    _rewarm_retry: bool = False,
) -> dict[str, Any]:
    """Single REST 1.1 request — used by `rest_call` (no retry/cache)."""
    url = f"{base}/{path.lstrip('/')}"
    had_cached_session = False
    if method == "GET" and not _rewarm_retry:
        _lk = getattr(SessionStore.get(), "lookup", None)
        if callable(_lk):
            _cand = _lk(auth_token)
            if asyncio.iscoroutine(_cand):
                had_cached_session = (await _cand) is not None
    need_rewarm = False

    async with pooled_client(auth_token) as client:
        try:
            ct0, _ = await warm_session(client, auth_token)
        except InvalidTokenError as e:
            return _invalid_token_response(e, auth_token)
        except WarmNetworkError as e:
            res_w: dict[str, Any] = {
                "status": "error",
                "http_status": getattr(e, "http_status", 502),
                "error": f"warm-up failed: {e.message}",
                "data": None,
            }
            if getattr(e, "no_retry", False):
                res_w["_no_retry"] = True
            return res_w

        headers = {
            **headers_for_token(auth_token),
            "authorization": f"Bearer {WEB_BEARER}",
            "x-csrf-token": ct0,
        }
        try:
            tid = await TIDProvider.get().generate(method, _urlparse(url).path, auth_token)
            if tid:
                headers["x-client-transaction-id"] = tid
        except Exception:  # noqa: BLE001
            pass

        try:
            if json_body is not None:
                headers["content-type"] = "application/json"
                resp = await client.request(method, url, headers=headers, json=json_body)
            elif method == "GET" and data is None:
                resp = await client.request(method, url, headers=headers)
            else:
                headers["content-type"] = "application/x-www-form-urlencoded"
                resp = await client.request(method, url, headers=headers, data=data or {})
        except Exception as exc:  # noqa: BLE001
            await ClientPool.get().invalidate(auth_token, all_proxies=False)
            return {
                "status": "error",
                "http_status": 502,
                "error": redact_proxy_creds(f"upstream request failed: {type(exc).__name__}: {exc}"),
                "data": None,
            }

        if resp.status_code >= 400:
            is_proxy_auth_or_quota = resp.status_code in (402, 407)
            if resp.status_code in (401, 403):
                all_p = resp.status_code == 401
                if all_p:
                    ResponseCache.get().invalidate_token(auth_token)
                await SessionStore.get().invalidate(auth_token, all_proxies=all_p)
                await ClientPool.get().invalidate(auth_token, all_proxies=all_p)
                if had_cached_session:
                    need_rewarm = True
            elif is_proxy_auth_or_quota:
                await ClientPool.get().invalidate(auth_token, all_proxies=False)
            if not need_rewarm:
                err_out = {
                    "status": "error",
                    "http_status": 502 if is_proxy_auth_or_quota else resp.status_code,
                    "error": redact_proxy_creds(resp.text[:1000]),
                    "data": None,
                }
                if is_proxy_auth_or_quota:
                    err_out["_no_retry"] = True
                return err_out

        if not need_rewarm:
            try:
                payload = resp.json()
            except json.JSONDecodeError:
                payload = {"raw": redact_proxy_creds(resp.text[:1000])}

            return {
                "status": "ok",
                "http_status": resp.status_code,
                "data": payload,
            }

    return await _rest_call_once(
        path,
        auth_token,
        method=method,
        data=data,
        json_body=json_body,
        base=base,
        _rewarm_retry=True,
    )


# ──────────────────────────── DM (REST 1.1 internal) ────────────────────────────


async def dm_call(
    path: str,
    auth_token: str,
    *,
    method: str = "GET",
    params: Optional[dict[str, Any]] = None,
    data: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    with_dm_defaults: bool = True,
) -> dict[str, Any]:
    """DM caller dengan retry pada transient errors."""
    return await with_retry(
        _dm_call_once,
        path,
        auth_token,
        method=method,
        params=params,
        data=data,
        json_body=json_body,
        with_dm_defaults=with_dm_defaults,
    )


async def _dm_call_once(
    path: str,
    auth_token: str,
    *,
    method: str = "GET",
    params: Optional[dict[str, Any]] = None,
    data: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    with_dm_defaults: bool = True,
    _rewarm_retry: bool = False,
) -> dict[str, Any]:
    """Single REST 1.1 DM request — used by `dm_call` (no retry)."""
    url = f"{DM_BASE}/{path.lstrip('/')}"

    final_params: dict[str, Any] = {}
    if with_dm_defaults and method == "GET":
        final_params.update(DM_DEFAULT_PARAMS)
    if params:
        final_params.update(params)

    had_cached_session = False
    if method == "GET" and not _rewarm_retry:
        _lk = getattr(SessionStore.get(), "lookup", None)
        if callable(_lk):
            _cand = _lk(auth_token)
            if asyncio.iscoroutine(_cand):
                had_cached_session = (await _cand) is not None
    need_rewarm = False

    async with pooled_client(auth_token) as client:
        try:
            ct0, _ = await warm_session(client, auth_token)
        except InvalidTokenError as e:
            return _invalid_token_response(e, auth_token)
        except WarmNetworkError as e:
            res_w: dict[str, Any] = {
                "status": "error",
                "http_status": getattr(e, "http_status", 502),
                "error": f"warm-up failed: {e.message}",
                "data": None,
            }
            if getattr(e, "no_retry", False):
                res_w["_no_retry"] = True
            return res_w

        headers = {
            **headers_for_token(auth_token),
            "authorization": f"Bearer {WEB_BEARER}",
            "x-csrf-token": ct0,
            "referer": "https://x.com/messages",
        }
        try:
            tid = await TIDProvider.get().generate(method, _urlparse(url).path, auth_token)
            if tid:
                headers["x-client-transaction-id"] = tid
        except Exception:  # noqa: BLE001
            pass

        try:
            if json_body is not None:
                headers["content-type"] = "application/json"
                resp = await client.request(
                    method, url, headers=headers, params=final_params, json=json_body,
                )
            elif data is not None:
                headers["content-type"] = "application/x-www-form-urlencoded"
                resp = await client.request(
                    method, url, headers=headers, params=final_params, data=data,
                )
            else:
                resp = await client.request(method, url, headers=headers, params=final_params)
        except Exception as exc:  # noqa: BLE001
            await ClientPool.get().invalidate(auth_token, all_proxies=False)
            return {
                "status": "error",
                "http_status": 502,
                "error": redact_proxy_creds(f"upstream request failed: {type(exc).__name__}: {exc}"),
                "data": None,
            }

        try:
            payload = resp.json()
        except json.JSONDecodeError:
            payload = {"raw": redact_proxy_creds(resp.text[:1000])}

        if resp.status_code >= 400:
            is_proxy_auth_or_quota = resp.status_code in (402, 407)
            if resp.status_code in (401, 403):
                all_p = resp.status_code == 401
                if all_p:
                    ResponseCache.get().invalidate_token(auth_token)
                await SessionStore.get().invalidate(auth_token, all_proxies=all_p)
                await ClientPool.get().invalidate(auth_token, all_proxies=all_p)
                if had_cached_session:
                    need_rewarm = True
            elif is_proxy_auth_or_quota:
                await ClientPool.get().invalidate(auth_token, all_proxies=False)
            if not need_rewarm:
                err_out = {
                    "status": "error",
                    "http_status": 502 if is_proxy_auth_or_quota else resp.status_code,
                    "error": payload,
                    "data": None,
                }
                if is_proxy_auth_or_quota:
                    err_out["_no_retry"] = True
                return err_out

        if not need_rewarm:
            return {
                "status": "ok",
                "http_status": resp.status_code,
                "data": payload,
            }

    return await _dm_call_once(
        path,
        auth_token,
        method=method,
        params=params,
        data=data,
        json_body=json_body,
        with_dm_defaults=with_dm_defaults,
        _rewarm_retry=True,
    )


def _safe_sort_key(x: str) -> tuple[int, str]:
    s = str(x)
    if s.isdigit():
        return (0, s.zfill(30))
    return (1, s)


def dm_conv_id_for(me: str, other: str) -> str:
    """1-1 DM conversation_id format = sorted(me, other) joined dengan '-'."""
    a, b = sorted([str(me), str(other)], key=_safe_sort_key)
    return f"{a}-{b}"


def build_dm_new2_payload(
    me: str,
    conv_id: Optional[str],
    recipient_ids: Optional[list[str]],
    text: str,
    media_id: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> dict[str, Any]:
    """Build POST /i/api/1.1/dm/new2.json body.

    Either `conv_id` (existing conversation) atau `recipient_ids` (auto-create)
    harus di-set.
    """
    payload: dict[str, Any] = {
        "request_id": secrets.token_hex(16),
        "text": text,
        "cards_platform": "Web-12",
        "include_cards": 1,
        "include_quote_count": True,
        "dm_users": True,
    }
    if conv_id:
        payload["conversation_id"] = conv_id
    if recipient_ids:
        # X dm/new2.json expects recipient_ids sebagai CSV string, bukan list.
        # Kalau list yg dikirim, X balas: "recipient_ids: '' is not a valid String".
        payload["recipient_ids"] = ",".join(str(r) for r in recipient_ids)
    if media_id:
        payload["media_id"] = media_id
    if reply_to:
        payload["reply_to_dm_id"] = reply_to
    return payload


# ──────────────────────────── Media upload (chunked) ────────────────────────────


async def media_upload(
    auth_token: str,
    file_bytes: bytes,
    media_type: str,
    media_category: Optional[str] = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Chunked upload (INIT/APPEND/FINALIZE [+ STATUS polling]) ke upload.x.com.

    MEDIA_PROXY_EXEMPT (default aktif): upload dibuat **direct tanpa proxy**
    untuk hemat kuota proxy — video bisa puluhan MB. Session direct memakai
    cookie hasil warm_session (yang tetap lewat jalur proxy). Kalau direct
    gagal karena network, fallback otomatis ke session ber-proxy; error yang
    dikembalikan X sendiri (4xx dsb.) TIDAK memicu fallback.

    Returns:
        {status, media_id?, processing_info?, data}
    """
    # Warm session via jalur proxy dulu (konsisten dengan crawl). Kalau
    # proxy mati dan MEDIA_PROXY_EXEMPT aktif, warm ulang via direct —
    # session upload memang direct, jadi konsisten.
    has_proxy = bool(proxy_for_token(auth_token))
    proxy_warm_ok = False
    had_cached_proxy_session = False
    _lk_up = getattr(SessionStore.get(), "lookup", None)
    if callable(_lk_up):
        _cand_up = _lk_up(auth_token)
        if asyncio.iscoroutine(_cand_up):
            had_cached_proxy_session = (await _cand_up) is not None
    jar: dict[str, str] = {}
    ct0: Optional[str] = None
    warm_err_status: int = 502
    warm_err_msg: str = "warm-up failed"
    try:
        async with pooled_client(auth_token) as client:
            try:
                ct0, _ = await warm_session(client, auth_token)
                proxy_warm_ok = True
            except InvalidTokenError as e:
                ResponseCache.get().invalidate_token(auth_token)
                return {
                    "status": "invalid",
                    "http_status": e.http_status,
                    "error": e.message,
                    "data": None,
                }
            jar = {c.name: c.value for c in client.cookies.jar}
    except Exception as exc:  # noqa: BLE001 — network/proxy error, lanjut direct bila ada proxy
        st = getattr(exc, "http_status", 502)
        warm_err_status = st if isinstance(st, int) and st >= 400 else 502
        warm_err_msg = redact_proxy_creds(getattr(exc, "message", None) or str(exc))
        if warm_err_status != 429:
            await ClientPool.get().invalidate(auth_token, all_proxies=False)
        if has_proxy:
            logging.getLogger("xapi.upload").info(
                "warm via proxy gagal (%s) — coba warm direct", warm_err_msg)

    if ct0 is None:
        if not (has_proxy and MEDIA_PROXY_EXEMPT):
            return {
                "status": "error",
                "http_status": warm_err_status,
                "error": (
                    f"warm-up failed: {warm_err_msg}"
                    if not has_proxy
                    else f"warm-up failed (proxy down, MEDIA_PROXY_EXEMPT off): {warm_err_msg}"
                ),
                "data": None,
            }
        direct0 = _direct_session(auth_token, {}, 30.0)
        direct_ctx_tok = set_request_proxy(_DIRECT_PROXY_SENTINEL)
        try:
            ct0, _ = await warm_session(direct0, auth_token)
            jar = {c.name: c.value for c in direct0.cookies.jar}
        except InvalidTokenError as e:
            ResponseCache.get().invalidate_token(auth_token)
            await SessionStore.get().invalidate(auth_token, all_proxies=True)
            await ClientPool.get().invalidate(auth_token, all_proxies=True)
            return {
                "status": "invalid",
                "http_status": e.http_status,
                "error": e.message,
                "data": None,
            }
        except Exception as exc:  # noqa: BLE001
            st = getattr(exc, "http_status", 502)
            return {
                "status": "error",
                "http_status": st if isinstance(st, int) and st >= 400 else 502,
                "error": redact_proxy_creds(f"warm-up failed (proxy & direct): {exc}"),
                "data": None,
            }
        finally:
            reset_request_proxy(direct_ctx_tok)
            try:
                await direct0.close()
            except Exception:  # noqa: BLE001
                pass

    base_headers = {
        **headers_for_token(auth_token),
        "authorization": f"Bearer {WEB_BEARER}",
        "x-csrf-token": ct0,
    }

    if has_proxy and MEDIA_PROXY_EXEMPT:
        direct = _direct_session(auth_token, jar, timeout)
        try:
            direct_res = await _upload_chunks(
                direct, base_headers, file_bytes, media_type, media_category, max_poll_seconds=timeout)
            direct_res.pop("_proxy_err", None)
            if (
                direct_res.get("status") == "ok"
                or not proxy_warm_ok
                or direct_res.get("http_status") not in (401, 403, 429, 500, 502, 503, 504)
            ):
                return direct_res
            logging.getLogger("xapi.upload").warning(
                "upload direct ditolak upstream (HTTP %s) — fallback ke proxy",
                direct_res.get("http_status"),
            )
        except Exception as exc:  # noqa: BLE001
            if not proxy_warm_ok:
                return {
                    "status": "error",
                    "http_status": 502,
                    "error": redact_proxy_creds(f"upload failed (proxy & direct): {type(exc).__name__}: {exc}"),
                    "data": None,
                }
            logging.getLogger("xapi.upload").warning(
                "upload direct gagal (%s: %s) — fallback ke proxy",
                type(exc).__name__, redact_proxy_creds(str(exc)))
        finally:
            try:
                await direct.close()
            except Exception:  # noqa: BLE001
                pass

    for _up_attempt in range(2):
        need_up_rewarm = False
        if _up_attempt == 0 and not had_cached_proxy_session:
            _lk_retry = getattr(SessionStore.get(), "lookup", None)
            if callable(_lk_retry):
                _cand_retry = _lk_retry(auth_token)
                if asyncio.iscoroutine(_cand_retry):
                    had_cached_proxy_session = (await _cand_retry) is not None
        async with pooled_client(auth_token) as client:
            try:
                pooled_ct0, _ = await warm_session(client, auth_token)
                base_headers = {**base_headers, "x-csrf-token": pooled_ct0}
            except InvalidTokenError as e:
                ResponseCache.get().invalidate_token(auth_token)
                return {
                    "status": "invalid",
                    "http_status": e.http_status,
                    "error": e.message,
                    "data": None,
                }
            except WarmNetworkError as e:
                return {
                    "status": "error",
                    "http_status": getattr(e, "http_status", 502),
                    "error": f"warm-up failed: {e.message}",
                    "data": None,
                }
            old_timeout = getattr(client, "timeout", 20.0)
            client.timeout = timeout
            try:
                up_res = await _upload_chunks(
                    client, base_headers, file_bytes, media_type, media_category, max_poll_seconds=timeout)
                if up_res.get("status") != "ok":
                    if up_res.get("http_status") in (401, 403):
                        all_p = up_res.get("http_status") == 401
                        if all_p:
                            ResponseCache.get().invalidate_token(auth_token)
                        await SessionStore.get().invalidate(auth_token, all_proxies=all_p)
                        await ClientPool.get().invalidate(auth_token, all_proxies=all_p)
                        if _up_attempt == 0 and had_cached_proxy_session and up_res.get("stage") == "INIT":
                            need_up_rewarm = True
                    elif up_res.pop("_proxy_err", False):
                        await ClientPool.get().invalidate(auth_token, all_proxies=False)
                if not need_up_rewarm:
                    return up_res
            except Exception as exc:  # noqa: BLE001
                await ClientPool.get().invalidate(auth_token, all_proxies=False)
                return {
                    "status": "error",
                    "http_status": 502,
                    "error": redact_proxy_creds(f"upload failed: {type(exc).__name__}: {exc}"),
                    "data": None,
                }
            finally:
                client.timeout = old_timeout

    return up_res


_CF_IP_BOUND_COOKIES = frozenset({"__cf_bm", "_cfuvid", "cf_clearance"})


def _direct_session(auth_token: str, jar: dict[str, str],
                    timeout: float) -> Any:
    """Session curl_cffi TANPA proxy — untuk jalur media (hemat kuota), tetap sinkron dengan profil browser.
    Buang cookie Cloudflare yang terikat IP proxy (`__cf_bm`, `_cfuvid`, `cf_clearance`)
    agar tidak ditolak 403 saat dikirim dari IP direct server."""
    prof = profile_for_token(auth_token)
    cookies = {"auth_token": auth_token, "ct0": gen_ct0()}
    if jar:
        cookies.update({k: v for k, v in jar.items() if k not in _CF_IP_BOUND_COOKIES})
    sess = CurlAsyncSession(
        cookies=cookies,
        headers=headers_for_token(auth_token),
        impersonate=prof["impersonate"],
        timeout=timeout,
        allow_redirects=True,
        trust_env=False,
    )
    return sess


async def _upload_chunks(
    client: Any,
    base_headers: dict[str, str],
    file_bytes: bytes,
    media_type: str,
    media_category: Optional[str],
    *,
    max_poll_seconds: float = 120.0,
) -> dict[str, Any]:
    """INIT/APPEND/FINALIZE/STATUS memakai session yang diberikan."""
    # 1. INIT
    init_params: dict[str, str] = {
        "command": "INIT",
        "total_bytes": str(len(file_bytes)),
        "media_type": media_type,
    }
    if media_category:
        init_params["media_category"] = media_category

    init_resp = await client.post(UPLOAD_BASE, headers=base_headers, data=init_params)
    if init_resp.status_code >= 400:
        return _upload_error(init_resp, "INIT")
    try:
        init_json = init_resp.json()
    except json.JSONDecodeError:
        return _upload_error(init_resp, "INIT")
    media_id = init_json.get("media_id_string") or str(init_json.get("media_id") or "")
    if not media_id:
        return _upload_error(init_resp, "INIT")

    # 2. APPEND chunks
    seg = 0
    for offset in range(0, len(file_bytes), CHUNK_SIZE):
        chunk = file_bytes[offset : offset + CHUNK_SIZE]
        mime = CurlMime()
        try:
            mime.addpart(
                "media",
                data=chunk,
                filename="blob",
                content_type="application/octet-stream",
            )
            ap_resp = await client.post(
                UPLOAD_BASE,
                headers=base_headers,
                data={
                    "command": "APPEND",
                    "media_id": media_id,
                    "segment_index": str(seg),
                },
                multipart=mime,
            )
        finally:
            mime.close()
        if ap_resp.status_code >= 400:
            return _upload_error(ap_resp, f"APPEND[{seg}]", media_id=media_id)
        seg += 1

    # 3. FINALIZE
    fin_resp = await client.post(
        UPLOAD_BASE,
        headers=base_headers,
        data={"command": "FINALIZE", "media_id": media_id},
    )
    if fin_resp.status_code >= 400:
        return _upload_error(fin_resp, "FINALIZE", media_id=media_id)
    try:
        fin_json = fin_resp.json()
    except json.JSONDecodeError:
        return _upload_error(fin_resp, "FINALIZE", media_id=media_id)

    # 4. STATUS polling kalau processing async (dibatasi max_poll_seconds)
    info = fin_json.get("processing_info")
    poll_deadline = time.monotonic() + max_poll_seconds
    while info and info.get("state") in ("pending", "in_progress"):
        if time.monotonic() >= poll_deadline:
            return {
                "status": "error",
                "error": f"media processing timed out after {max_poll_seconds}s",
                "stage": "PROCESSING",
                "media_id": media_id,
                "data": fin_json,
            }
        wait_secs = max(1, min(int(info.get("check_after_secs") or 2), 15))
        await asyncio.sleep(wait_secs)
        st_resp = await client.get(
            UPLOAD_BASE,
            headers=base_headers,
            params={"command": "STATUS", "media_id": media_id},
        )
        if st_resp.status_code >= 400:
            return _upload_error(st_resp, "STATUS", media_id=media_id)
        try:
            fin_json = st_resp.json()
        except json.JSONDecodeError:
            return _upload_error(st_resp, "STATUS", media_id=media_id)
        info = fin_json.get("processing_info")

    if info and info.get("state") == "failed":
        return {
            "status": "error",
            "error": info.get("error") or info,
            "stage": "PROCESSING",
            "media_id": media_id,
            "data": fin_json,
        }

    return {"status": "ok", "http_status": 200, "data": fin_json}


# ──────────────────────────── Internal helpers ────────────────────────────


def _invalid_token_response(e: InvalidTokenError, auth_token: str) -> dict[str, Any]:
    ResponseCache.get().invalidate_token(auth_token)
    return {
        "status": "invalid",
        "http_status": e.http_status,
        "error": e.message,
        "data": None,
    }


def _upload_error(resp: Any, stage: str, *, media_id: Optional[str] = None) -> dict[str, Any]:
    raw_st = getattr(resp, "status_code", None)
    norm_st = 502 if (not isinstance(raw_st, int) or raw_st < 400 or raw_st in (402, 407)) else raw_st
    err: dict[str, Any] = {
        "status": "error",
        "http_status": norm_st,
        "error": redact_proxy_creds(resp.text[:1000]),
        "stage": stage,
        "data": None,
    }
    if media_id:
        err["media_id"] = media_id
    if isinstance(raw_st, int) and raw_st in (402, 407):
        err["_proxy_err"] = True
    return err
