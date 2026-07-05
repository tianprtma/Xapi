"""Auto-generated router module for the Bookmarks resource family.

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


router = APIRouter(tags=["Bookmarks"])


class BookmarkBody(BaseModel):
    tweet_id: str = Field(..., pattern=r"^\d+$")


@router.get("/2/users/{user_id}/bookmarks")
async def v2_my_bookmarks(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/{id}/bookmarks → Bookmarks (own only)."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "count": max_results,
        "includePromotedContent": False,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("Bookmarks", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.post("/2/users/{user_id}/bookmarks")
async def v2_bookmark(
    body: BookmarkBody,
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call(
        "CreateBookmark",
        {"tweet_id": body.tweet_id},
        tok,
        method="POST",
    )
    # CF-gated: fallback Playwright UI click (TID di-inject otomatis oleh X client)
    if result["status"] == "error" and result.get("http_status") == 404:
        # Resolve author handle untuk navigate
        author = await tweet_author_handle(body.tweet_id, tok)
        nav = f"https://x.com/{author or 'i/web'}/status/{body.tweet_id}"
        result = await click_action_via_browser(
            tok, nav,
            click_selector='[data-testid="bookmark"]',
            match_response_substr="/CreateBookmark",
        )
    return write_finalize(result, raw=bool(raw))


@router.get("/2/users/{user_id}/bookmarks/folders")
async def v2_bookmarks_folders(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/users/{id}/bookmarks/folders — list bookmark folders."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"count": max_results}
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("BookmarkFoldersSlice", variables, tok)
    return finalize(result, format_bookmark_folders, raw=bool(raw))


@router.get("/2/users/{user_id}/bookmarks/folders/{folder_id}")
async def v2_bookmarks_folder_by_id(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    folder_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/users/{id}/bookmarks/folders/{folder_id} — tweets in folder."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "bookmark_collection_id": folder_id,
        "count": max_results,
        "includePromotedContent": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("BookmarkFolderTimeline", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.delete("/2/users/{user_id}/bookmarks/{tweet_id}")
async def v2_unbookmark(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call(
        "DeleteBookmark",
        {"tweet_id": tweet_id},
        tok,
        method="POST",
    )
    if result["status"] == "error" and result.get("http_status") == 404:
        author = await tweet_author_handle(tweet_id, tok)
        nav = f"https://x.com/{author or 'i/web'}/status/{tweet_id}"
        result = await click_action_via_browser(
            tok, nav,
            click_selector='[data-testid="removeBookmark"]',
            match_response_substr="/DeleteBookmark",
        )
    return write_finalize(result, raw=bool(raw))

