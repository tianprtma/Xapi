"""Auto-generated router module for the Trends resource family.

Routes were mechanically extracted from main.py by build_routers.py — when
adding new endpoints, add them directly to this file and import the router
in main.py via `app.include_router`.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from formatter import (
    format_birdwatch_batsignal,
    format_birdwatch_note_result,
    format_birdwatch_notes_slice,
    format_bookmark_folders,
    format_community,
    format_dm_events,
    format_dm_send_result,
    format_error,
    format_tweet,
    format_tweet_collection,
    format_user,
)
from playwright_search import (
    action_via_browser,
    click_action_via_browser,
    fetch_via_browser,
    search_via_browser,
)
from session_cache import SessionStore
from tid_provider import TIDProvider

from ..auth import (
    InvalidTokenError,
    extract_bearer,
    extract_user_id_from_twid,
    login_with_auth_token,
    make_client,
    resolve_me_id,
    warm_session,
)
from ..clients import (
    build_dm_new2_payload,
    dm_call,
    dm_conv_id_for,
    graphql_call,
    media_upload,
    rest_call,
)
from ..config import (
    DM_BASE,
    DM_DEFAULT_PARAMS,
    GQL_META,
    NEW_GQL_REASON,
    OAUTH2_USER_CTX_REASON,
    REST_BASE,
    SearchType,
    UPLOAD_BASE,
    WEB_BEARER,
)
from ..playwright_helpers import resolve_screen_name, tweet_author_handle
from ..responses import finalize, stub_501, wrap, write_finalize


router = APIRouter(tags=["Trends"])


async def _trends_impl(
    woeid: int,
    authorization: Optional[str],
    auth_token: Optional[str],
    raw: int,
) -> JSONResponse:
    """Shared backend for /2/trends + /2/trends/by/woeid/{woeid}."""
    tok = extract_bearer(authorization, auth_token)
    result = await rest_call(f"trends/place.json?id={woeid}", tok, method="GET")
    if raw:
        return wrap(result)
    if result.get("status") == "ok":
        try:
            payload = result["data"]
            trends = payload[0].get("trends", []) if isinstance(payload, list) else []
            return JSONResponse(
                status_code=200,
                content={
                    "data": [
                        {"name": t.get("name"), "url": t.get("url"), "tweet_volume": t.get("tweet_volume")}
                        for t in trends
                    ],
                    "meta": {
                        "woeid": woeid,
                        "as_of": payload[0].get("as_of") if isinstance(payload, list) else None,
                    },
                },
            )
        except Exception:  # noqa: BLE001
            return wrap(result)
    return wrap(result)


@router.get("/2/trends")
async def v2_trends(
    woeid: int = Query(1, description="WOEID region; 1=worldwide"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """[LEGACY] Trends. Pakai GET /2/trends/by/woeid/{woeid}."""
    return await _trends_impl(woeid, authorization, auth_token, raw)


@router.get("/2/trends/by/woeid/{woeid}")
async def v2_trends_by_woeid(
    woeid: int = PathParam(..., description="WOEID region (1=worldwide, 23424977=US, 23424775=ID)"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Canonical: GET /2/trends/by/woeid/{woeid}."""
    return await _trends_impl(woeid, authorization, auth_token, raw)


@router.get("/2/users/personalized_trends")
async def v2_personalized_trends(
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Personalized trends untuk current user (REST 1.1 trends/personalized)."""
    tok = extract_bearer(authorization, auth_token)
    result = await rest_call("trends/personalized.json", tok, method="GET")
    if raw:
        return wrap(result)
    if result.get("status") == "ok":
        try:
            payload = result["data"]
            trends = payload[0].get("trends", []) if isinstance(payload, list) else []
            return JSONResponse(
                status_code=200,
                content={
                    "data": [
                        {"name": t.get("name"), "url": t.get("url"), "tweet_volume": t.get("tweet_volume")}
                        for t in trends
                    ],
                    "meta": {"as_of": payload[0].get("as_of") if isinstance(payload, list) else None},
                },
            )
        except Exception:  # noqa: BLE001
            return wrap(result)
    return wrap(result)

