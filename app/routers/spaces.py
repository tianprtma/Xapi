"""Auto-generated router module for the Spaces resource family.

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


router = APIRouter(tags=["Spaces"])


@router.get(
    "/2/spaces",
    summary="Bulk space lookup",
    description="Fan-out lookup multiple Spaces by comma-separated IDs — calls `AudioSpaceById` per ID.",
)
async def v2_spaces_lookup(
    ids: str = Query(..., description="comma-separated space IDs"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Fan-out lookup multiple spaces — calls AudioSpaceById per ID."""
    tok = extract_bearer(authorization, auth_token)
    id_list = [s.strip() for s in ids.split(",") if s.strip()]
    if not id_list:
        return JSONResponse(status_code=400, content=format_error(
            "Bad Request", "ids must contain at least 1 value", "bad_request", 400,
        ))

    import asyncio
    async def _one(sid: str):
        return await graphql_call("AudioSpaceById", {
            "id": sid,
            "isMetatagsQuery": False,
            "withReplays": True,
            "withListeners": True,
        }, tok)

    results = await asyncio.gather(*[_one(s) for s in id_list])
    if raw:
        return JSONResponse(status_code=200, content={"results": results})
    data = [r.get("data") for r in results if r.get("status") == "ok"]
    return JSONResponse(status_code=200, content={"data": data})


@router.get(
    "/2/spaces/topics",
    summary="Browse space topics",
    description="List browseable Space topics — `BrowseSpaceTopics` GraphQL.",
)
async def v2_spaces_topics(
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Browseable Space topics — BrowseSpaceTopics."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("BrowseSpaceTopics", {}, tok)
    return write_finalize(result, raw=bool(raw))


@router.get(
    "/2/spaces/{space_id}",
    summary="Get space",
    description="Single Space lookup by ID — `AudioSpaceById` GraphQL (includes replays + listeners).",
)
async def v2_space_by_id(
    space_id: str = PathParam(...),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Single space lookup — AudioSpaceById."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("AudioSpaceById", {
        "id": space_id,
        "isMetatagsQuery": False,
        "withReplays": True,
        "withListeners": True,
    }, tok)
    return write_finalize(result, raw=bool(raw))


@router.get("/2/spaces/{space_id}/buyers")
async def v2_space_buyers(space_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(feature="space_buyers", reason=OAUTH2_USER_CTX_REASON)


@router.get("/2/spaces/by/creator_ids")
async def v2_spaces_by_creator() -> JSONResponse:
    return stub_501(
        feature="spaces_by_creator",
        reason=(
            "X web client tidak meng-expose AudioSpacesByCreator GraphQL op. "
            "Workaround: pakai /2/users/{id}/tweets dgn filter card_uri='audio_space'."
        ),
    )


@router.get("/2/spaces/{space_id}/tweets")
async def v2_space_tweets(space_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(
        feature="space_tweets",
        reason=(
            "X web client tidak meng-expose AudioSpaceTweets GraphQL op. "
            "Workaround: SearchTimeline dengan q=https://x.com/i/spaces/{id}."
        ),
    )

