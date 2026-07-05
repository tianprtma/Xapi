"""Auto-generated router module for the Users resource family.

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
from ..responses import batch_finalize, finalize, stub_501, wrap, write_finalize


router = APIRouter(tags=["Users"])


class FollowBody(BaseModel):
    target_user_id: str = Field(..., pattern=r"^\d+$")


class MuteBody(BaseModel):
    target_user_id: str = Field(..., pattern=r"^\d+$")


class BlockBody(BaseModel):
    target_user_id: str = Field(..., pattern=r"^\d+$")


class PinTweetBody(BaseModel):
    tweet_id: str


@router.get("/2/users")
async def v2_users_bulk(
    ids: str = Query(..., description="Comma-separated user IDs, max 100"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/users?ids=1,2,3 — fan-out via UserByRestId GraphQL."""
    tok = extract_bearer(authorization, auth_token)
    id_list = [i.strip() for i in ids.split(",") if i.strip()][:100]
    if not id_list:
        return JSONResponse(status_code=400, content=format_error("Bad Request", "ids kosong", "bad_request", 400))

    import asyncio

    async def _one(uid: str) -> dict[str, Any]:
        try:
            r = await graphql_call("UserByRestId", {"userId": uid, "withSafetyModeUserFields": True}, tok)
            return {"id": uid, "data": r.get("data"), "status": r.get("status", "ok")}
        except Exception as e:  # noqa: BLE001
            return {"id": uid, "status": "error", "error": str(e)}

    results = await asyncio.gather(*[_one(u) for u in id_list])

    if raw:
        return JSONResponse(status_code=200, content={"data": results})

    data, errors = [], []
    for r in results:
        if r.get("status") != "ok":
            errors.append({"id": r["id"], "title": "Lookup Failed", "type": "not_found"})
            continue
        formatted = format_user(r.get("data") or {})
        if "errors" in formatted:
            errors.append({"id": r["id"], **formatted["errors"][0]})
        else:
            data.append(formatted["data"])
    out: dict[str, Any] = {"data": data, "meta": {"result_count": len(data)}}
    if errors: out["errors"] = errors
    return batch_finalize(out)


@router.get("/2/users/by")
async def v2_users_by_usernames(
    usernames: str = Query(..., description="Comma-separated usernames, max 100"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/users/by?usernames=a,b — fan-out via UserByScreenName."""
    tok = extract_bearer(authorization, auth_token)
    name_list = [n.strip().lstrip("@") for n in usernames.split(",") if n.strip()][:100]
    if not name_list:
        return JSONResponse(status_code=400, content=format_error("Bad Request", "usernames kosong", "bad_request", 400))

    import asyncio

    async def _one(name: str) -> dict[str, Any]:
        return await graphql_call("UserByScreenName", {"screen_name": name}, tok)

    results = await asyncio.gather(*[_one(n) for n in name_list], return_exceptions=True)

    if raw:
        return JSONResponse(status_code=200, content={"data": [r if isinstance(r, dict) else str(r) for r in results]})

    data, errors = [], []
    for n, r in zip(name_list, results):
        if isinstance(r, Exception) or (isinstance(r, dict) and r.get("status") != "ok"):
            errors.append({"username": n, "title": "Lookup Failed", "type": "not_found"})
            continue
        f = format_user(r.get("data") or {})
        if "errors" in f:
            errors.append({"username": n, **f["errors"][0]})
        else:
            data.append(f["data"])
    out: dict[str, Any] = {"data": data, "meta": {"result_count": len(data)}}
    if errors: out["errors"] = errors
    return batch_finalize(out)


@router.get("/2/users/by/username/{username}")
async def v2_user_by_username(
    username: str = PathParam(..., min_length=1, max_length=15, pattern=r"^[A-Za-z0-9_]+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/by/username/{username} → UserByScreenName.

    Username validation: 1-15 chars, alphanumeric + underscore (X handle format).
    """
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("UserByScreenName", {"screen_name": username}, tok)
    return finalize(result, format_user, raw=bool(raw))


@router.get("/2/users/me")
async def v2_users_me(
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/me — return profile dari Viewer."""
    tok = extract_bearer(authorization, auth_token)
    # Pakai UserByScreenName setelah resolve via /login
    login = await login_with_auth_token(tok)
    if login["status"] != "valid":
        if raw:
            return JSONResponse(status_code=401, content=login)
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", login.get("error", ""), "unauthorized", 401),
        )

    if raw:
        return JSONResponse(status_code=200, content=login)

    u = login.get("user") or {}
    return JSONResponse(
        status_code=200,
        content={
            "data": {
                "id": u.get("id"),
                "name": u.get("name"),
                "username": u.get("screen_name"),
                "created_at": u.get("created_at"),
                "verified": u.get("verified") or False,
                "protected": u.get("protected") or False,
                "public_metrics": {
                    "followers_count": u.get("followers_count"),
                    "following_count": u.get("friends_count"),
                    "tweet_count": u.get("statuses_count"),
                },
            }
        },
    )


@router.get("/2/users/public_keys")
async def v2_users_public_keys() -> JSONResponse:
    return stub_501(feature="users_public_keys", reason="X PassKey/E2EE public keys belum di-discover.")


@router.get("/2/users/reposts_of_me")
async def v2_reposts_of_me(
    max_results: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Posts yang me-retweet tweet kita (best-effort via SearchTimeline)."""
    tok = extract_bearer(authorization, auth_token)
    # Resolve current user screen_name
    login = await login_with_auth_token(tok)
    if login["status"] != "valid":
        return JSONResponse(status_code=401, content=format_error("Unauthorized", "auth_token invalid", "unauthorized", 401))
    handle = (login.get("user") or {}).get("screen_name")
    if not handle:
        return JSONResponse(status_code=500, content=format_error("Internal", "unresolved screen_name", "internal", 500))
    q = f"filter:nativeretweets from:{handle}"
    pw = await search_via_browser(auth_token=tok, q=q, search_type="Latest")
    result = {
        "engine": "playwright",
        "status": pw["status"],
        "http_status": pw.get("http_status", 200),
        "data": pw.get("data"),
        "error": pw.get("error"),
    }
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/users/search")
async def v2_users_search(
    query: str = Query(..., min_length=1),
    max_results: int = Query(20, ge=1, le=100),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/users/search?query= — SearchTimeline (product=People)."""
    tok = extract_bearer(authorization, auth_token)
    pw = await search_via_browser(auth_token=tok, q=query, search_type="People")
    result = {
        "engine": "playwright",
        "status": pw["status"],
        "http_status": pw.get("http_status", 200),
        "data": pw.get("data"),
        "error": pw.get("error"),
    }
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.delete("/2/users/{source_user_id}/blocking/{target_user_id}")
async def v2_unblock(
    source_user_id: str = PathParam(..., pattern=r"^\d+$"),
    target_user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await rest_call(
        "blocks/destroy.json",
        tok,
        data={"user_id": target_user_id},
    )
    # CF-gated: fallback Playwright UI click (TID di-inject otomatis)
    if result["status"] == "error" and result.get("http_status") == 404:
        handle = await resolve_screen_name(target_user_id, tok)
        if handle:
            result = await click_action_via_browser(
                tok, f"https://x.com/{handle}",
                click_selector='[data-testid$="-unblock"]',
                confirm_selector='[data-testid="confirmationSheetConfirm"]',
                match_response_substr="blocks/destroy",
            )
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/users/{source_user_id}/following/{target_user_id}")
async def v2_unfollow(
    source_user_id: str = PathParam(..., pattern=r"^\d+$"),
    target_user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await rest_call(
        "friendships/destroy.json",
        tok,
        data={"user_id": target_user_id},
    )
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/users/{source_user_id}/muting/{target_user_id}")
async def v2_unmute(
    source_user_id: str = PathParam(..., pattern=r"^\d+$"),
    target_user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await rest_call(
        "mutes/users/destroy.json",
        tok,
        data={"user_id": target_user_id},
    )
    return write_finalize(result, raw=bool(raw))


@router.get("/2/users/{user_id}")
async def v2_user_by_id(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/{id} → UserByRestId (Playwright, CF-gated)."""
    tok = extract_bearer(authorization, auth_token)
    pw = await fetch_via_browser(
        auth_token=tok,
        navigate_url=f"https://x.com/i/user/{user_id}",
        match_path=["/UserByRestId", "/UserByScreenName"],
    )
    result = {
        "status": pw["status"],
        "http_status": pw.get("http_status", 200),
        "operation": "UserByRestId",
        "engine": "playwright",
        "data": pw.get("data"),
        "error": pw.get("error"),
    }
    return finalize(result, format_user, raw=bool(raw))


@router.get(
    "/2/users/{user_id}/affiliates",
    summary="Affiliates (Business team)",
    description="X Premium Business profile team members via `UserBusinessProfileTeamTimeline` GraphQL.",
)
async def v2_user_affiliates(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    count: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """X Premium Business "team members" — UserBusinessProfileTeamTimeline."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "userId": user_id,
        "count": count,
        "teamName": "NotAssigned",
        "includePromotedContent": False,
        "withClientEventToken": False,
        "withVoice": True,
    }
    if cursor:
        variables["cursor"] = cursor
    result = await graphql_call("UserBusinessProfileTeamTimeline", variables, tok)
    return write_finalize(result, raw=bool(raw))


@router.get("/2/users/{user_id}/blocking")
async def v2_user_blocking(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/users/{id}/blocking — BlockedAccountsAll (own only, user_id harus = self)."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"count": max_results, "includePromotedContent": False}
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("BlockedAccountsAll", variables, tok)
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.post("/2/users/{user_id}/blocking")
async def v2_block(
    body: BlockBody,
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await rest_call(
        "blocks/create.json",
        tok,
        data={
            "user_id": body.target_user_id,
            "include_profile_interstitial_type": "1",
            "skip_status": "1",
        },
    )
    return write_finalize(result, raw=bool(raw))


@router.get("/2/users/{user_id}/followers")
async def v2_user_followers(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/{id}/followers → Followers (Playwright fallback)."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "userId": user_id, "count": max_results, "includePromotedContent": False,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("Followers", variables, tok)
    if result["status"] == "ok":
        return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))
    handle = await resolve_screen_name(user_id, tok)
    if not handle:
        return JSONResponse(status_code=404, content=format_error("Not Found", "user_id not found", "not_found", 404))
    pw = await fetch_via_browser(
        auth_token=tok,
        navigate_url=f"https://x.com/{handle}/followers",
        match_path="/Followers",
    )
    result = {
        "status": pw["status"],
        "http_status": pw.get("http_status", 200),
        "operation": "Followers",
        "engine": "playwright",
        "data": pw.get("data"),
        "error": pw.get("error"),
    }
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.get("/2/users/{user_id}/following")
async def v2_user_following(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/{id}/following → Following."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "userId": user_id, "count": max_results, "includePromotedContent": False,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("Following", variables, tok)
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.post("/2/users/{user_id}/following")
async def v2_follow(
    body: FollowBody,
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Follow user. Body: {target_user_id}."""
    tok = extract_bearer(authorization, auth_token)
    result = await rest_call(
        "friendships/create.json",
        tok,
        data={
            "user_id": body.target_user_id,
            "include_profile_interstitial_type": "1",
            "include_blocking": "1",
            "include_blocked_by": "1",
            "include_followed_by": "1",
            "skip_status": "1",
        },
    )
    return write_finalize(result, raw=bool(raw))


@router.get("/2/users/{user_id}/liked_tweets")
async def v2_user_liked_tweets(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/{id}/liked_tweets → Likes."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "userId": user_id, "count": max_results, "includePromotedContent": False,
        "withClientEventToken": False, "withBirdwatchNotes": False,
        "withVoice": True, "withV2Timeline": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("Likes", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/users/{user_id}/media")
async def v2_user_media(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/{id}/media → UserMedia."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "userId": user_id, "count": max_results, "includePromotedContent": False,
        "withClientEventToken": False, "withBirdwatchNotes": False,
        "withVoice": True, "withV2Timeline": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("UserMedia", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/users/{user_id}/mentions")
async def v2_mentions(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    username: Optional[str] = Query(None, description="Override username (kalau bukan dari user_id)"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    Mirror: GET /2/users/{id}/mentions → SearchTimeline (@handle).
    NB: butuh username — auto-resolve via UserByRestId kalau tidak di-pass.
    """
    tok = extract_bearer(authorization, auth_token)
    handle = username
    if not handle:
        # Resolve via Playwright UserByRestId
        from playwright_search import fetch_via_browser
        ur = await fetch_via_browser(tok, f"https://x.com/i/user/{user_id}", "/UserByRestId")
        if ur.get("status") == "ok":
            try:
                handle = ur["data"]["data"]["user"]["result"]["core"]["screen_name"]
            except Exception:  # noqa: BLE001
                pass
    if not handle:
        return JSONResponse(
            status_code=400,
            content=format_error("Bad Request", "username unresolved", "bad_request", 400),
        )
    pw = await search_via_browser(auth_token=tok, q=f"@{handle}", search_type="Latest")
    result = {
        "engine": "playwright",
        "status": pw["status"],
        "http_status": pw.get("http_status", 200),
        "data": pw.get("data"),
        "error": pw.get("error"),
    }
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/users/{user_id}/muting")
async def v2_user_muting(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/users/{id}/muting — MutedAccounts (own only)."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"count": max_results, "includePromotedContent": False}
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("MutedAccounts", variables, tok)
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.post("/2/users/{user_id}/muting")
async def v2_mute(
    body: MuteBody,
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await rest_call(
        "mutes/users/create.json",
        tok,
        data={"user_id": body.target_user_id},
    )
    return write_finalize(result, raw=bool(raw))


@router.post("/2/users/{user_id}/pinned_tweets")
async def v2_pin_tweet(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    body: PinTweetBody = ...,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Pin tweet ke profile. Body: {tweet_id}."""
    tok = extract_bearer(authorization, auth_token)
    # PinTweet pakai REST 1.1 (bukan GraphQL) di X v2 → tetapi kita punya GraphQL
    result = await graphql_call("PinTweet", {"tweet_id": body.tweet_id}, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/users/{user_id}/pinned_tweets/{tweet_id}")
async def v2_unpin_tweet(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Unpin tweet."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("UnpinTweet", {"tweet_id": tweet_id}, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.get("/2/users/{user_id}/public_keys")
async def v2_user_public_keys(user_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
    return stub_501(feature="user_public_keys", reason="X PassKey/E2EE public keys belum di-discover.")


@router.post("/2/users/{user_id}/public_keys")
async def v2_user_public_keys_post(user_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
    return stub_501(feature="user_public_keys_post", reason="X PassKey/E2EE public keys belum di-discover.")


@router.get("/2/users/{user_id}/tweets")
async def v2_user_tweets(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/{id}/tweets → UserTweets."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "userId": user_id, "count": max_results, "includePromotedContent": True,
        "withQuickPromoteEligibilityTweetFields": True, "withVoice": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("UserTweets", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/users/{user_id}/tweets/replies")
async def v2_user_tweets_replies(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/users/{id}/tweets/replies → UserTweetsAndReplies (Playwright fallback)."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "userId": user_id, "count": max_results, "includePromotedContent": True,
        "withCommunity": True, "withVoice": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("UserTweetsAndReplies", variables, tok)
    if result["status"] == "ok":
        return finalize(result, format_tweet_collection, raw=bool(raw))
    handle = await resolve_screen_name(user_id, tok)
    if not handle:
        return JSONResponse(status_code=404, content=format_error("Not Found", "user_id not found", "not_found", 404))
    pw = await fetch_via_browser(
        auth_token=tok,
        navigate_url=f"https://x.com/{handle}",
        match_path=["/UserTweetsAndReplies"],
        click_selector=f"a[href='/{handle}/with_replies']",
        timeout=30.0,
    )
    result = {
        "status": pw["status"],
        "http_status": pw.get("http_status", 200),
        "operation": "UserTweetsAndReplies",
        "engine": "playwright",
        "data": pw.get("data"),
        "error": pw.get("error"),
    }
    return finalize(result, format_tweet_collection, raw=bool(raw))

