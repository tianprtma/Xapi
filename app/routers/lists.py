"""Auto-generated router module for the Lists resource family.

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


router = APIRouter(tags=["Lists"])


class CreateListBody(BaseModel):
    name: str
    description: Optional[str] = ""
    is_private: bool = False


class UpdateListBody(BaseModel):
    list_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    is_private: Optional[bool] = None


class ListMemberBody(BaseModel):
    list_id: str
    user_id: str


class UpdateListPathBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_private: Optional[bool] = None


class PinnedListBody(BaseModel):
    list_id: str = Field(..., pattern=r"^\d+$")


@router.post("/2/lists")
async def v2_create_list(
    body: CreateListBody,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Create list."""
    tok = extract_bearer(authorization, auth_token)
    variables = {
        "name": body.name,
        "description": body.description or "",
        "isPrivate": body.is_private,
    }
    result = await graphql_call("CreateList", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.put("/2/lists")
async def v2_update_list(
    body: UpdateListBody,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """[LEGACY] Update list. Body: {list_id, name?, description?, is_private?}. Pakai PUT /2/lists/{id}."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"listId": body.list_id}
    if body.name is not None:
        variables["name"] = body.name
    if body.description is not None:
        variables["description"] = body.description
    if body.is_private is not None:
        variables["isPrivate"] = body.is_private
    result = await graphql_call("UpdateList", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.get("/2/lists/by/owner/{user_id}")
async def v2_lists_owned(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """[LEGACY] List milik current user. Pakai GET /2/users/{id}/owned_lists."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"count": max_results}
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("ListsManagementPageTimeline", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.delete("/2/lists/{list_id}")
async def v2_delete_list(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Delete list."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("DeleteList", {"listId": list_id}, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.get("/2/lists/{list_id}")
async def v2_list_detail(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Detail satu list → ListByRestId."""
    tok = extract_bearer(authorization, auth_token)
    variables = {"listId": list_id}
    result = await graphql_call("ListByRestId", variables, tok)
    return finalize(result, lambda g: g, raw=bool(raw))


@router.put("/2/lists/{list_id}")
async def v2_update_list_canonical(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    body: UpdateListPathBody = ...,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror canonical: PUT /2/lists/{id}. Body: {name?, description?, is_private?}."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"listId": list_id}
    if body.name is not None:
        variables["name"] = body.name
    if body.description is not None:
        variables["description"] = body.description
    if body.is_private is not None:
        variables["isPrivate"] = body.is_private
    result = await graphql_call("UpdateList", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.get("/2/lists/{list_id}/followers")
async def v2_list_followers(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/lists/{id}/followers — subscriber timeline."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"listId": list_id, "count": max_results}
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("ListSubscribers", variables, tok)
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.get("/2/lists/{list_id}/members")
async def v2_list_members(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/lists/{id}/members → ListMembers."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "listId": list_id,
        "count": max_results,
        "withSafetyModeUserFields": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("ListMembers", variables, tok)
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.post("/2/lists/{list_id}/members")
async def v2_list_add_member(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    body: ListMemberBody = ...,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Add user to list. Body: {user_id}."""
    tok = extract_bearer(authorization, auth_token)
    variables = {"listId": list_id, "userId": body.user_id}
    result = await graphql_call("ListAddMember", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/lists/{list_id}/members/{user_id}")
async def v2_list_remove_member(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Remove user from list."""
    tok = extract_bearer(authorization, auth_token)
    variables = {"listId": list_id, "userId": user_id}
    result = await graphql_call("ListRemoveMember", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/lists/{list_id}/pinned")
async def v2_unpin_list(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """[LEGACY] Unpin list. Pakai DELETE /2/users/{id}/pinned_lists/{list_id}."""
    tok = extract_bearer(authorization, auth_token)
    variables = {"pinnedTimelineItem": {"id": list_id, "pinned_timeline_type": "List"}}
    result = await graphql_call("UnpinTimeline", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.post("/2/lists/{list_id}/pinned")
async def v2_pin_list(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """[LEGACY] Pin list. Pakai POST /2/users/{id}/pinned_lists."""
    tok = extract_bearer(authorization, auth_token)
    variables = {"pinnedTimelineItem": {"id": list_id, "pinned_timeline_type": "List"}}
    result = await graphql_call("PinTimeline", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.get("/2/lists/{list_id}/tweets")
async def v2_list_tweets(
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/lists/{id}/tweets → ListLatestTweetsTimeline."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "listId": list_id,
        "count": max_results,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("ListLatestTweetsTimeline", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/users/{user_id}/followed_lists")
async def v2_followed_lists(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """List subscriptions (followed lists) — `ListsManagementPageTimeline`.

    Note: X web client only exposes my-own list management (auth user). Server
    ignores `user_id` if it doesn't match the auth session — same behavior as
    `/2/lists/by/owner/{user_id}` for non-self lookup.
    """
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("ListsManagementPageTimeline", {"count": max_results}, tok)
    return write_finalize(result, raw=bool(raw))


@router.post("/2/users/{user_id}/followed_lists")
async def v2_follow_list(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    list_id: str = Query(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """POST /2/users/{id}/followed_lists?list_id=… — subscribe to list."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("ListSubscribe", {"listId": list_id}, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/users/{user_id}/followed_lists/{list_id}")
async def v2_unfollow_list(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """DELETE /2/users/{id}/followed_lists/{list_id} — unsubscribe."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("ListUnsubscribe", {"listId": list_id}, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.get("/2/users/{user_id}/list_memberships")
async def v2_list_memberships(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/users/{id}/list_memberships — list mana saja user jadi member."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"userId": user_id, "count": max_results}
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("ListMemberships", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/users/{user_id}/owned_lists")
async def v2_user_owned_lists(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Canonical: GET /2/users/{id}/owned_lists."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"count": max_results}
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("ListsManagementPageTimeline", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/users/{user_id}/pinned_lists")
async def v2_user_pinned_lists(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/users/{id}/pinned_lists → PinnedTimelines."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {}
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("PinnedTimelines", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.post("/2/users/{user_id}/pinned_lists")
async def v2_pin_list_canonical(
    body: PinnedListBody,
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Canonical: POST /2/users/{id}/pinned_lists. Body: {list_id}."""
    tok = extract_bearer(authorization, auth_token)
    variables = {"pinnedTimelineItem": {"id": body.list_id, "pinned_timeline_type": "List"}}
    result = await graphql_call("PinTimeline", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/users/{user_id}/pinned_lists/{list_id}")
async def v2_unpin_list_canonical(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    list_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Canonical: DELETE /2/users/{id}/pinned_lists/{list_id}."""
    tok = extract_bearer(authorization, auth_token)
    variables = {"pinnedTimelineItem": {"id": list_id, "pinned_timeline_type": "List"}}
    result = await graphql_call("UnpinTimeline", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw))

