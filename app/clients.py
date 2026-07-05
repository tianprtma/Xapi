"""HTTP clients: GraphQL, REST 1.1, DM, media upload.

Semua function balikin shape standar:
    {status: ok|invalid|error, http_status, data?, error?, cookies, tokens}
"""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any, Optional
from urllib.parse import urlparse as _urlparse

from fastapi import HTTPException

from session_cache import SessionStore
from tid_provider import TIDProvider

from .auth import (
    InvalidTokenError,
    api_headers,
    make_client,
    warm_session,
)
from .client_pool import pooled_client
from .config import (
    CHUNK_SIZE,
    DEFAULT_HEADERS,
    DM_BASE,
    DM_DEFAULT_PARAMS,
    GQL_META,
    GRAPHQL_BASE,
    REST_BASE,
    UPLOAD_BASE,
    WEB_BEARER,
)
from .response_cache import ResponseCache
from .retry import with_retry


# ──────────────────────────── GraphQL ────────────────────────────


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


async def _graphql_call_once(
    operation: str,
    variables: dict[str, Any],
    auth_token: str,
    method: str = "GET",
) -> dict[str, Any]:
    """Single GraphQL request — no retry, no cache (used by `graphql_call`)."""
    meta = GQL_META.get(operation)
    if not meta:
        raise HTTPException(status_code=500, detail=f"unknown GraphQL op: {operation}")

    url = f"{GRAPHQL_BASE}/{meta['queryId']}/{operation}"

    async with pooled_client(auth_token) as client:
        try:
            ct0, _ = await warm_session(client, auth_token)
        except InvalidTokenError as e:
            return _invalid_token_response(e, auth_token)

        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(meta.get("features", {})),
        }
        if meta.get("fieldToggles"):
            params["fieldToggles"] = json.dumps(meta["fieldToggles"])

        headers = api_headers(ct0)
        try:
            tid = await TIDProvider.get().generate(method, _urlparse(url).path)
            if tid:
                headers["x-client-transaction-id"] = tid
        except Exception:  # noqa: BLE001
            pass

        if method == "GET":
            resp = await client.get(url, headers=headers, params=params)
        else:
            resp = await client.post(url, headers=headers, json={
                "variables": variables,
                "features": meta.get("features", {}),
                "fieldToggles": meta.get("fieldToggles", {}),
                "queryId": meta["queryId"],
            })

        if resp.status_code != 200:
            if resp.status_code in (401, 403):
                await SessionStore.get().invalidate(auth_token)
            return {
                "status": "error",
                "http_status": resp.status_code,
                "error": resp.text[:1000],
                "data": None,
            }

        try:
            payload = resp.json()
        except json.JSONDecodeError:
            return {
                "status": "error",
                "http_status": resp.status_code,
                "error": "non-JSON response",
                "raw": resp.text[:1000],
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": 200,
            "operation": operation,
            "data": payload,
        }


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
) -> dict[str, Any]:
    """Single REST 1.1 request — used by `rest_call` (no retry/cache)."""
    url = f"{base}/{path.lstrip('/')}"

    async with pooled_client(auth_token) as client:
        try:
            ct0, _ = await warm_session(client, auth_token)
        except InvalidTokenError as e:
            return _invalid_token_response(e, auth_token)

        headers = {
            **DEFAULT_HEADERS,
            "authorization": f"Bearer {WEB_BEARER}",
            "x-csrf-token": ct0,
        }
        try:
            tid = await TIDProvider.get().generate(method, _urlparse(url).path)
            if tid:
                headers["x-client-transaction-id"] = tid
        except Exception:  # noqa: BLE001
            pass

        if json_body is not None:
            headers["content-type"] = "application/json"
            resp = await client.request(method, url, headers=headers, json=json_body)
        else:
            headers["content-type"] = "application/x-www-form-urlencoded"
            resp = await client.request(method, url, headers=headers, data=data or {})

        if resp.status_code >= 400:
            return {
                "status": "error",
                "http_status": resp.status_code,
                "error": resp.text[:1000],
                "data": None,
            }

        try:
            payload = resp.json()
        except json.JSONDecodeError:
            payload = {"raw": resp.text[:1000]}

        return {
            "status": "ok",
            "http_status": resp.status_code,
            "data": payload,
        }


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
) -> dict[str, Any]:
    """Single REST 1.1 DM request — used by `dm_call` (no retry)."""
    url = f"{DM_BASE}/{path.lstrip('/')}"

    final_params: dict[str, Any] = {}
    if with_dm_defaults and method == "GET":
        final_params.update(DM_DEFAULT_PARAMS)
    if params:
        final_params.update(params)

    async with pooled_client(auth_token) as client:
        try:
            ct0, _ = await warm_session(client, auth_token)
        except InvalidTokenError as e:
            return _invalid_token_response(e, auth_token)

        headers = {
            **DEFAULT_HEADERS,
            "authorization": f"Bearer {WEB_BEARER}",
            "x-csrf-token": ct0,
        }
        try:
            tid = await TIDProvider.get().generate(method, _urlparse(url).path)
            if tid:
                headers["x-client-transaction-id"] = tid
        except Exception:  # noqa: BLE001
            pass

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

        try:
            payload = resp.json()
        except json.JSONDecodeError:
            payload = {"raw": resp.text[:1000]}

        if resp.status_code >= 400:
            if resp.status_code in (401, 403):
                await SessionStore.get().invalidate(auth_token)
            return {
                "status": "error",
                "http_status": resp.status_code,
                "error": payload,
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": resp.status_code,
            "data": payload,
        }


def dm_conv_id_for(me: str, other: str) -> str:
    """1-1 DM conversation_id format = sorted(me, other) joined dengan '-'."""
    def _safe_sort_key(x: str) -> tuple[int, str]:
        try:
            return (0, int(x))
        except (ValueError, TypeError):
            return (1, x)

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

    Returns:
        {status, media_id?, processing_info?, data}
    """
    async with pooled_client(auth_token) as client:
        try:
            ct0, _ = await warm_session(client, auth_token)
        except InvalidTokenError as e:
            return {
                "status": "invalid",
                "http_status": e.http_status,
                "error": e.message,
                "data": None,
            }

        base_headers = {
            **DEFAULT_HEADERS,
            "authorization": f"Bearer {WEB_BEARER}",
            "x-csrf-token": ct0,
        }
        client.timeout = timeout

        # 1. INIT
        init_params: dict[str, str] = {
            "command": "INIT",
            "total_bytes": str(len(file_bytes)),
            "media_type": media_type,
        }
        if media_category:
            init_params["media_category"] = media_category

        init_resp = await client.post(UPLOAD_BASE, headers=base_headers, params=init_params)
        if init_resp.status_code >= 400:
            return _upload_error(init_resp, "INIT")
        init_json = init_resp.json()
        media_id = init_json.get("media_id_string") or str(init_json.get("media_id"))

        # 2. APPEND chunks
        seg = 0
        for offset in range(0, len(file_bytes), CHUNK_SIZE):
            chunk = file_bytes[offset : offset + CHUNK_SIZE]
            ap_resp = await client.post(
                UPLOAD_BASE,
                headers=base_headers,
                data={
                    "command": "APPEND",
                    "media_id": media_id,
                    "segment_index": str(seg),
                },
                files={"media": ("blob", chunk, "application/octet-stream")},
            )
            if ap_resp.status_code >= 400:
                return _upload_error(ap_resp, f"APPEND[{seg}]", media_id=media_id)
            seg += 1

        # 3. FINALIZE
        fin_resp = await client.post(
            UPLOAD_BASE,
            headers=base_headers,
            params={"command": "FINALIZE", "media_id": media_id},
        )
        if fin_resp.status_code >= 400:
            return _upload_error(fin_resp, "FINALIZE", media_id=media_id)
        fin_json = fin_resp.json()

        # 4. STATUS polling kalau processing async
        info = fin_json.get("processing_info")
        while info and info.get("state") in ("pending", "in_progress"):
            await asyncio.sleep(int(info.get("check_after_secs") or 2))
            st_resp = await client.get(
                UPLOAD_BASE,
                headers=base_headers,
                params={"command": "STATUS", "media_id": media_id},
            )
            if st_resp.status_code >= 400:
                return _upload_error(st_resp, "STATUS", media_id=media_id)
            fin_json = st_resp.json()
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
    return {
        "status": "invalid",
        "http_status": e.http_status,
        "error": e.message,
        "data": None,
    }


def _upload_error(resp: Any, stage: str, *, media_id: Optional[str] = None) -> dict[str, Any]:
    err: dict[str, Any] = {
        "status": "error",
        "http_status": resp.status_code,
        "error": resp.text[:1000],
        "stage": stage,
        "data": None,
    }
    if media_id:
        err["media_id"] = media_id
    return err
