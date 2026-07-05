"""Auto-generated router module for the Tweets resource family.

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


router = APIRouter(tags=["Tweets"])


class CreateTweetBody(BaseModel):
    text: str = Field(..., max_length=4000)
    reply_to: Optional[str] = Field(None, description="in_reply_to_tweet_id")
    quote_tweet_id: Optional[str] = None
    media_ids: Optional[list[str]] = None


class LikeBody(BaseModel):
    tweet_id: str = Field(..., pattern=r"^\d+$")


class RetweetBody(BaseModel):
    tweet_id: str = Field(..., pattern=r"^\d+$")


@router.get("/2/tweets")
async def v2_tweets_bulk(
    ids: str = Query(..., description="Comma-separated tweet IDs, max 100"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/tweets?ids=1,2,3 — fan-out via TweetResultByRestId."""
    tok = extract_bearer(authorization, auth_token)
    id_list = [i.strip() for i in ids.split(",") if i.strip()][:100]
    if not id_list:
        return JSONResponse(status_code=400, content=format_error("Bad Request", "ids kosong", "bad_request", 400))

    import asyncio

    async def _one(tid: str) -> dict[str, Any]:
        return await graphql_call(
            "TweetResultByRestId",
            {"tweetId": tid, "withCommunity": False, "includePromotedContent": False, "withVoice": False},
            tok,
        )

    results = await asyncio.gather(*[_one(t) for t in id_list], return_exceptions=True)

    if raw:
        return JSONResponse(status_code=200, content={"data": [r if isinstance(r, dict) else str(r) for r in results]})

    data: list[dict] = []
    users: dict[str, dict] = {}
    media: dict[str, dict] = {}
    refs: dict[str, dict] = {}
    errors: list[dict] = []
    for tid, r in zip(id_list, results):
        if isinstance(r, Exception) or (isinstance(r, dict) and r.get("status") != "ok"):
            errors.append({"id": tid, "title": "Lookup Failed", "detail": str(r)[:200], "type": "not_found"})
            continue
        formatted = format_tweet(r.get("data") or {})
        if "errors" in formatted:
            errors.append({"id": tid, **formatted["errors"][0]})
            continue
        d = formatted.get("data")
        if d:
            data.append(d)
        for k, lst in (formatted.get("includes") or {}).items():
            target = {"users": users, "media": media, "tweets": refs}[k]
            for item in lst:
                key = item.get("id") or item.get("media_key")
                if key and key not in target:
                    target[key] = item

    out: dict[str, Any] = {"data": data, "meta": {"result_count": len(data)}}
    inc = {}
    if users: inc["users"] = list(users.values())
    if media: inc["media"] = list(media.values())
    if refs: inc["tweets"] = list(refs.values())
    if inc: out["includes"] = inc
    if errors: out["errors"] = errors
    return batch_finalize(out)


@router.post("/2/tweets")
async def v2_create_tweet(
    body: CreateTweetBody,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Create tweet / reply / quote. Body: {text, reply_to?, quote_tweet_id?, media_ids?}."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "tweet_text": body.text,
        "dark_request": False,
        "media": {"media_entities": [], "possibly_sensitive": False},
        "semantic_annotation_ids": [],
        "disallowed_reply_controls": [],
    }
    if body.media_ids:
        variables["media"]["media_entities"] = [
            {"media_id": mid, "tagged_users": []} for mid in body.media_ids
        ]
    if body.reply_to:
        variables["reply"] = {
            "in_reply_to_tweet_id": body.reply_to,
            "exclude_reply_user_ids": [],
        }
    if body.quote_tweet_id:
        variables["attachment_url"] = f"https://twitter.com/i/status/{body.quote_tweet_id}"

    result = await graphql_call("CreateTweet", variables, tok, method="POST")
    return write_finalize(result, raw=bool(raw), formatter=format_tweet, success_status=201)


@router.get("/2/tweets/search/recent")
async def v2_tweets_search_recent(
    query: str = Query(..., min_length=1, alias="query"),
    max_results: int = Query(20, ge=1, le=100),
    next_token: Optional[str] = Query(None),
    type: SearchType = Query("Latest"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/tweets/search/recent → SearchTimeline via Playwright."""
    tok = extract_bearer(authorization, auth_token)
    try:
        pw = await search_via_browser(auth_token=tok, q=query, search_type=type)
        result = {
            "engine": "playwright",
            "status": pw["status"],
            "http_status": pw.get("http_status", 200),
            "data": pw.get("data"),
            "error": pw.get("error"),
        }
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=502,
            content=format_error("Upstream Error", str(e), "upstream_error", 502),
        )
    fmt = format_tweet_collection if type != "People" else (lambda g: format_tweet_collection(g, item="user"))
    return finalize(result, fmt, raw=bool(raw))


@router.delete("/2/tweets/{tweet_id}")
async def v2_delete_tweet(
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call(
        "DeleteTweet",
        {"tweet_id": tweet_id, "dark_request": False},
        tok,
        method="POST",
    )
    return write_finalize(result, raw=bool(raw))


@router.get("/2/tweets/{tweet_id}")
async def v2_tweet_by_id(
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/tweets/{id} → TweetResultByRestId."""
    tok = extract_bearer(authorization, auth_token)
    variables = {
        "tweetId": tweet_id,
        "withCommunity": False,
        "includePromotedContent": False,
        "withVoice": False,
    }
    result = await graphql_call("TweetResultByRestId", variables, tok)
    return finalize(result, format_tweet, raw=bool(raw))


@router.get("/2/tweets/{tweet_id}/detail")
async def v2_tweet_detail(
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    cursor: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/tweets/{id}/detail → TweetDetail (with replies thread)."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "focalTweetId": tweet_id,
        "with_rux_injections": False,
        "includePromotedContent": True,
        "withCommunity": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withBirdwatchNotes": True,
        "withVoice": True,
        "withV2Timeline": True,
    }
    if cursor:
        variables["cursor"] = cursor
    result = await graphql_call("TweetDetail", variables, tok)
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.put("/2/tweets/{tweet_id}/hidden")
async def v2_hide_reply(
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """PUT /2/tweets/{id}/hidden — hide/unhide reply via ModerateTweet."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call("ModerateTweet", {"tweetId": tweet_id}, tok, method="POST")
    return write_finalize(result, raw=bool(raw))


@router.get("/2/tweets/{tweet_id}/liking_users")
async def v2_liking_users(
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/tweets/{id}/liking_users → Favoriters."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "tweetId": tweet_id,
        "count": max_results,
        "includePromotedContent": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("Favoriters", variables, tok)
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.get("/2/tweets/{tweet_id}/quote_tweets")
async def v2_quote_tweets(
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/tweets/{id}/quote_tweets → SearchTimeline (filter:quote)."""
    tok = extract_bearer(authorization, auth_token)
    q = f"quoted_tweet_id:{tweet_id}"
    pw = await search_via_browser(auth_token=tok, q=q, search_type="Latest")
    result = {
        "engine": "playwright",
        "status": pw["status"],
        "http_status": pw.get("http_status", 200),
        "data": pw.get("data"),
        "error": pw.get("error"),
    }
    return finalize(result, format_tweet_collection, raw=bool(raw))


@router.get("/2/tweets/{tweet_id}/retweeted_by")
async def v2_retweeted_by(
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Mirror: GET /2/tweets/{id}/retweeted_by → Retweeters."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "tweetId": tweet_id,
        "count": max_results,
        "includePromotedContent": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("Retweeters", variables, tok)
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.get("/2/tweets/{tweet_id}/retweets")
async def v2_tweet_retweets(
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """GET /2/tweets/{id}/retweets — alias dari /retweeted_by (Retweeters)."""
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {
        "tweetId": tweet_id, "count": max_results, "includePromotedContent": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token
    result = await graphql_call("Retweeters", variables, tok)
    return finalize(result, lambda g: format_tweet_collection(g, item="user"), raw=bool(raw))


@router.post("/2/users/{user_id}/likes")
async def v2_like(
    body: LikeBody,
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Like tweet. Body: {tweet_id}. user_id di path harus = id auth user."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call(
        "FavoriteTweet",
        {"tweet_id": body.tweet_id},
        tok,
        method="POST",
    )
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/users/{user_id}/likes/{tweet_id}")
async def v2_unlike(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call(
        "UnfavoriteTweet",
        {"tweet_id": tweet_id},
        tok,
        method="POST",
    )
    return write_finalize(result, raw=bool(raw))


@router.post("/2/users/{user_id}/retweets")
async def v2_retweet(
    body: RetweetBody,
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call(
        "CreateRetweet",
        {"tweet_id": body.tweet_id, "dark_request": False},
        tok,
        method="POST",
    )
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/users/{user_id}/retweets/by/source_tweet_id/{source_tweet_id}")
async def v2_unretweet_canonical(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    source_tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Canonical: DELETE /2/users/{id}/retweets/{source_tweet_id}."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call(
        "DeleteRetweet",
        {"source_tweet_id": source_tweet_id, "dark_request": False},
        tok,
        method="POST",
    )
    return write_finalize(result, raw=bool(raw))


@router.delete("/2/users/{user_id}/retweets/{tweet_id}")
async def v2_unretweet(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
    tweet_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """[LEGACY] Pakai DELETE /2/users/{id}/retweets/{source_tweet_id}."""
    tok = extract_bearer(authorization, auth_token)
    result = await graphql_call(
        "DeleteRetweet",
        {"source_tweet_id": tweet_id, "dark_request": False},
        tok,
        method="POST",
    )
    return write_finalize(result, raw=bool(raw))

