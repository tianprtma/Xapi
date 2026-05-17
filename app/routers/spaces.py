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


@router.get("/2/spaces")
async def v2_spaces_lookup(ids: str = Query(...)) -> JSONResponse:
    return stub_501(
        feature="spaces_lookup",
        reason=NEW_GQL_REASON + " Operation: AudioSpaceById (fan-out per ID).",
    )


@router.get("/2/spaces/by/creator_ids")
async def v2_spaces_by_creator() -> JSONResponse:
    return stub_501(
        feature="spaces_by_creator",
        reason=NEW_GQL_REASON + " Operation: AudioSpacesByCreator.",
    )


@router.get("/2/spaces/search")
async def v2_spaces_search() -> JSONResponse:
    return stub_501(
        feature="spaces_search",
        reason=NEW_GQL_REASON + " Operation: AudioSpaceSearch.",
    )


@router.get("/2/spaces/{space_id}")
async def v2_space_by_id(space_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(
        feature="space_by_id",
        reason=NEW_GQL_REASON + " Operation: AudioSpaceById.",
    )


@router.get("/2/spaces/{space_id}/buyers")
async def v2_space_buyers(space_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(feature="space_buyers", reason=OAUTH2_USER_CTX_REASON)


@router.get("/2/spaces/{space_id}/tweets")
async def v2_space_tweets(space_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(
        feature="space_tweets",
        reason=NEW_GQL_REASON + " Operation: AudioSpaceTweets.",
    )

