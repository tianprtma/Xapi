"""Auto-generated router module for the Timelines resource family.

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


router = APIRouter(tags=["Timelines"])


@router.get("/2/home_timeline")
async def v2_home_timeline(
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Extra: HomeTimeline (For You)."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "count": max_results,
        "includePromotedContent": True,
        "latestControlAvailable": True,
        "requestContext": "launch",
        "withCommunity": True,
        "seenTweetIds": [],
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("HomeTimeline", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/users/{user_id}/timelines/reverse_chronological")
async def v2_home_latest(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/{id}/timelines/reverse_chronological → HomeLatestTimeline."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "count": max_results,
        "includePromotedContent": True,
        "latestControlAvailable": True,
        "requestContext": "launch",
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("HomeLatestTimeline", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))

