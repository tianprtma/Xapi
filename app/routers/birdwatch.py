"""Auto-generated router module for the Birdwatch resource family.

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


router = APIRouter(tags=["Birdwatch"])


class BirdwatchNoteCreateBody(BaseModel):
    tweet_id: str = Field(..., pattern=r"^\d+$")
    is_media_note: bool = Field(False)
    is_helpful_for_all_posts: bool = Field(False)
    data: dict[str, Any] = Field(..., description="Note data v1 schema")


class BirdwatchRatingBody(BaseModel):
    note_id: str
    tweet_id: str = Field(..., pattern=r"^\d+$")
    data: dict[str, Any] = Field(..., description="Rating data v2")
    rating_source: Optional[str] = None
    source_platform: Optional[str] = None
    for_live_note: bool = Field(False)
    suggestion: Optional[str] = None


@router.post("/2/evaluate_note")
async def v2_evaluate_note(
    body: BirdwatchRatingBody,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """POST /2/evaluate_note — rate Birdwatch note."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "note_id": body.note_id,
        "tweet_id": body.tweet_id,
        "data_v2": body.data,
        "rating_source": body.rating_source,
        "source_platform": body.source_platform,
        "for_live_note": body.for_live_note,
        "suggestion": body.suggestion,
    }
    result = await graphql_call("BirdwatchCreateRating", variables, tok, method="POST")
    return write_finalize(
        result,
        raw=bool(raw),
        formatter=format_birdwatch_note_result,
        success_status=201,
    )


@router.post("/2/notes")
async def v2_notes_create(
    body: BirdwatchNoteCreateBody,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """POST /2/notes — create Birdwatch note."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "tweet_id": body.tweet_id,
        "is_media_note": body.is_media_note,
        "is_helpful_for_all_posts": body.is_helpful_for_all_posts,
        "data_v1": body.data,
    }
    result = await graphql_call("BirdwatchCreateNote", variables, tok, method="POST")
    return write_finalize(
        result,
        raw=bool(raw),
        formatter=format_birdwatch_note_result,
        success_status=201,
    )


@router.get("/2/notes/search/notes_written")
async def v2_notes_written(
    alias: str = Query(..., description="Birdwatch alias profile slug (required)"),
    max_results: int = Query(10, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/notes/search/notes_written — fetch notes by Birdwatch contributor alias."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"count": max_results, "alias": alias}
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("BirdwatchFetchContributorNotesSlice", variables, tok)
    return finalize(result, format_birdwatch_notes_slice, raw=bool(raw))


@router.get("/2/notes/search/posts_eligible_for_notes")
async def v2_notes_eligible_posts(
    tweet_id: str = Query(..., pattern=r"^\d+$", description="Target tweet id (required)"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/notes/search/posts_eligible_for_notes — fetch BatSignal for tweet_id."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("BirdwatchFetchBatSignal", {"tweet_id": tweet_id}, tok)
    return finalize(result, format_birdwatch_batsignal, raw=bool(raw))


@router.delete("/2/notes/{note_id}")
async def v2_notes_delete(
    note_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """DELETE /2/notes/{id} — delete Birdwatch note."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("BirdwatchDeleteNote", {"note_id": note_id}, tok, method="POST")
    return write_finalize(result, raw=bool(raw))

