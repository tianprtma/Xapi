"""Auto-generated router module for the Direct Messages resource family.

Routes were mechanically extracted from main.py by build_routers.py — when
adding new endpoints, add them directly to this file and import the router
in main.py via `app.include_router`.
"""

from __future__ import annotations

import secrets
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


router = APIRouter(tags=["Direct Messages"])


class DMConvCreateBody(BaseModel):
    conversation_type: str = Field("Group", description="Group | OneToOne")
    participant_ids: list[str] = Field(..., min_items=1)
    message: dict[str, Any] = Field(..., description="{text: '...'}")


class DMSendBody(BaseModel):
    text: str = Field(..., max_length=10000)
    media_id: Optional[str] = None
    attachments: Optional[list[dict[str, Any]]] = None
    reply_to_dm_event_id: Optional[str] = None


@router.get("/2/chat/conversations")
async def v2_chat_conversations() -> JSONResponse:
    return stub_501(feature="chat_conversations", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/group")
async def v2_chat_group_create() -> JSONResponse:
    return stub_501(feature="chat_group_create", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/group/initialize")
async def v2_chat_group_init() -> JSONResponse:
    return stub_501(feature="chat_group_init", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/keys")
async def v2_chat_keys(conversation_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(feature="chat_keys", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/members")
async def v2_chat_members(conversation_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(feature="chat_members", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/messages")
async def v2_chat_messages(conversation_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(feature="chat_messages", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/read")
async def v2_chat_read(conversation_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(feature="chat_read", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/typing")
async def v2_chat_typing(conversation_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(feature="chat_typing", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/media/upload/finalize")
async def v2_chat_mediafinalize() -> JSONResponse:
    return stub_501(feature="chat_media_finalize", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/media/upload/initialize")
async def v2_chat_media_init() -> JSONResponse:
    return stub_501(feature="chat_media_init", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/media/upload/{media_id}/append")
async def v2_chat_media_append(media_id: str = PathParam(...)) -> JSONResponse:
    return stub_501(feature="chat_media_append", reason=OAUTH2_USER_CTX_REASON)


@router.get("/2/chat/media/{media_id}/{media_hash_key}")
async def v2_chat_media(
    media_id: str = PathParam(...),
    media_hash_key: str = PathParam(...),
) -> JSONResponse:
    return stub_501(feature="chat_media", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/dm_conversations")
async def v2_dm_conv_create(
    body: DMConvCreateBody,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    POST /2/dm_conversations — create group conv + send first msg.
    Backend: REST 1.1 dm/new2.json (auto-creates conv jika belum ada).
    """
    tok = extract_bearer(authorization, auth_token)
    text = (body.message or {}).get("text") or ""
    if not text:
        return JSONResponse(
            status_code=400,
            content=format_error("Bad Request", "message.text required", "bad_request", 400),
        )
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )

    payload = build_dm_new2_payload(
        me=me,
        conv_id=None,
        recipient_ids=body.participant_ids,
        text=text,
    )
    if body.conversation_type.lower() in ("group", "groupdm"):
        payload["conversation_id"] = "-".join(sorted([me] + list(body.participant_ids), key=lambda x: int(x) if x.isdigit() else x))
    else:
        if len(body.participant_ids) == 1:
            payload["conversation_id"] = dm_conv_id_for(me, body.participant_ids[0])

    result = await dm_call("dm/new2.json", tok, method="POST", json_body=payload, with_dm_defaults=False)
    if raw:
        return wrap(result)
    if result["status"] != "ok":
        return write_finalize(result, raw=False)
    return JSONResponse(status_code=201, content=format_dm_send_result(result.get("data") or {}))


@router.get("/2/dm_conversations/media/{dm_id}/{media_id}/{resource_id}")
async def v2_dm_media(
    dm_id: str = PathParam(...),
    media_id: str = PathParam(...),
    resource_id: str = PathParam(...),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    filename: Optional[str] = Query(None, description="Optional filename hint (mis. `nhp0Nroa.jpg`)."),
):
    """Proxy stream binary DM media dari `ton.twitter.com` pakai sesi auth user.

    Path mengikuti shape `media_url_https`:
        https://ton.twitter.com/1.1/ton/data/dm/{dm_id}/{media_id}/{resource_id}
    """
    from fastapi.responses import Response

    tok = extract_bearer(authorization, auth_token)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )

    name = filename or resource_id
    upstream = f"https://ton.twitter.com/1.1/ton/data/dm/{dm_id}/{media_id}/{name}"

    headers = {
        "authorization": f"Bearer {WEB_BEARER}",
        "referer": "https://x.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    }
    cookies = {"auth_token": tok}

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        try:
            resp = await client.get(upstream, headers=headers, cookies=cookies)
        except httpx.HTTPError as e:
            return JSONResponse(
                status_code=502,
                content=format_error("Bad Gateway", f"upstream fetch failed: {e}", "upstream_error", 502),
            )

    if resp.status_code >= 400:
        return JSONResponse(
            status_code=resp.status_code,
            content=format_error(
                "Upstream error",
                f"ton.twitter.com returned {resp.status_code}",
                "upstream_error",
                resp.status_code,
            ),
        )

    ct = resp.headers.get("content-type", "application/octet-stream")
    out_headers = {
        "cache-control": "private, max-age=300",
        "content-disposition": f'inline; filename="{name}"',
    }
    return Response(content=resp.content, media_type=ct, headers=out_headers)


@router.get("/2/dm_conversations/with/{participant_id}/dm_events")
async def v2_dm_conv_with_participant(
    participant_id: str = PathParam(...),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    max_results: int = Query(50, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_conversations/with/{participant_id}/dm_events — events dari 1-1 conv.
    Backend: REST 1.1 dm/conversation/{me}-{other}.json
    """
    tok = extract_bearer(authorization, auth_token)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )
    conv_id = dm_conv_id_for(me, participant_id)
    params: dict[str, Any] = {"count": str(max_results), "context": "FETCH_DM_CONVERSATION"}
    if pagination_token:
        params["max_id"] = pagination_token
    result = await dm_call(f"dm/conversation/{conv_id}.json", tok, method="GET", params=params)
    if raw:
        return wrap(result)
    if result["status"] != "ok":
        return write_finalize(result, raw=False)
    return JSONResponse(status_code=200, content=format_dm_events(result.get("data") or {}))


@router.post("/2/dm_conversations/with/{participant_id}/messages")
async def v2_dm_send(
    participant_id: str = PathParam(...),
    body: DMSendBody = ...,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    POST /2/dm_conversations/with/{participant_id}/messages — kirim DM 1-1.
    Backend: REST 1.1 dm/new2.json (auto-create conv kalau belum ada).
    """
    tok = extract_bearer(authorization, auth_token)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )
    media_id = body.media_id
    if not media_id and body.attachments:
        media_id = (body.attachments[0] or {}).get("media_id")
    # X dm/new2.json — kalau pakai conversation_id + recipient_ids bersamaan,
    # X balas code 214 "Bad request." Pakai recipient_ids only (auto-create).
    payload = build_dm_new2_payload(
        me=me,
        conv_id=None,
        recipient_ids=[participant_id],
        text=body.text,
        media_id=media_id,
        reply_to=body.reply_to_dm_event_id,
    )
    result = await dm_call("dm/new2.json", tok, method="POST", json_body=payload, with_dm_defaults=False)
    if raw:
        return wrap(result)
    if result["status"] != "ok":
        return write_finalize(result, raw=False)
    return JSONResponse(status_code=201, content=format_dm_send_result(result.get("data") or {}))


@router.get("/2/dm_conversations/{conversation_id}/dm_events")
async def v2_dm_conv_events(
    conversation_id: str = PathParam(...),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    max_results: int = Query(50, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_conversations/{conversation_id}/dm_events — events dari conv (1-1 atau group).
    Backend: REST 1.1 dm/conversation/{conversation_id}.json
    """
    tok = extract_bearer(authorization, auth_token)
    params: dict[str, Any] = {"count": str(max_results), "context": "FETCH_DM_CONVERSATION"}
    if pagination_token:
        params["max_id"] = pagination_token
    result = await dm_call(f"dm/conversation/{conversation_id}.json", tok, method="GET", params=params)
    if raw:
        return wrap(result)
    if result["status"] != "ok":
        return write_finalize(result, raw=False)
    return JSONResponse(status_code=200, content=format_dm_events(result.get("data") or {}))


@router.post("/2/dm_conversations/{conversation_id}/messages")
async def v2_dm_send_to_conv(
    conversation_id: str = PathParam(...),
    body: DMSendBody = ...,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    POST /2/dm_conversations/{conversation_id}/messages — kirim ke conv tertentu (1-1 atau group).
    Backend: REST 1.1 dm/new2.json
    """
    tok = extract_bearer(authorization, auth_token)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )
    media_id = body.media_id
    if not media_id and body.attachments:
        media_id = (body.attachments[0] or {}).get("media_id")
    payload = build_dm_new2_payload(
        me=me,
        conv_id=conversation_id,
        recipient_ids=None,
        text=body.text,
        media_id=media_id,
        reply_to=body.reply_to_dm_event_id,
    )
    result = await dm_call("dm/new2.json", tok, method="POST", json_body=payload, with_dm_defaults=False)
    if raw:
        return wrap(result)
    if result["status"] != "ok":
        return write_finalize(result, raw=False)
    return JSONResponse(status_code=201, content=format_dm_send_result(result.get("data") or {}))


@router.get("/2/dm_events")
async def v2_dm_events(
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    max_results: int = Query(50, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    xchat_user_id: Optional[str] = Query(None),
    xchat_since_ms: Optional[int] = Query(None, ge=0),
    xchat_include_outbound: int = Query(1),
    xchat_include_reactions: int = Query(1),
    xchat_include_read_receipts: int = Query(0),
    include_requests: int = Query(
        1,
        description="Kalau 1 (default), DM dari Message Requests inbox (untrusted) ikut digabung. Set 0 untuk legacy behavior (trusted-only).",
    ),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_events — list semua DM events dari inbox.
    Backend: REST 1.1 dm/user_updates.json (cursor-based polling).

    Bila ``xchat_user_id`` diisi dengan numeric bot id, XChat plaintext rows
    dari OPFS chat.db ikut digabung ke ``data`` (event_type=MessageCreate,
    flag ``_xchat=True``). Worker bisa pakai itu untuk dedupe vs REST.

    Bila ``include_requests=1`` (default), Message Requests inbox (untrusted)
    juga dipanggil dan dimerge ke ``data``. Setiap MessageCreate yang ada
    info usernya akan punya flag ``_sender_follows_owner`` (true/false)
    biar worker bisa enforce policy follower-only tanpa lookup tambahan.
    """
    tok = extract_bearer(authorization, auth_token)
    params: dict[str, Any] = {"count": str(max_results), "active_conversations_only": "false"}
    if pagination_token:
        params["cursor"] = pagination_token
    result = await dm_call("dm/user_updates.json", tok, method="GET", params=params)
    if raw:
        return wrap(result)
    if result["status"] != "ok":
        return write_finalize(result, raw=False)
    out = format_dm_events(result.get("data") or {})

    if include_requests:
        # Untrusted inbox lives at a separate REST 1.1 path. It demands a
        # `max_id` parameter — we pass a max-snowflake-shaped value so the
        # newest page comes back. Failures are non-fatal (we degrade to
        # trusted-only) but tagged in meta for visibility.
        try:
            far = str(2 << 60)
            req_res = await dm_call(
                "dm/inbox_timeline/untrusted.json",
                tok,
                method="GET",
                params={"max_id": far, "count": str(max_results)},
            )
            if req_res.get("status") == "ok":
                req_out = format_dm_events(req_res.get("data") or {})
                seen = {e.get("id") for e in out.get("data") or []}
                merged = list(out.get("data") or [])
                for ev in req_out.get("data") or []:
                    if ev.get("id") in seen:
                        continue
                    merged.append(ev)
                out["data"] = merged
                # Merge users/conversations includes too.
                inc = out.setdefault("includes", {})
                req_inc = req_out.get("includes") or {}
                for kind in ("users", "dm_conversations"):
                    if not req_inc.get(kind):
                        continue
                    existing = {u["id"]: u for u in inc.get(kind, []) if u.get("id")}
                    for u in req_inc[kind]:
                        if u.get("id") and u["id"] not in existing:
                            existing[u["id"]] = u
                    inc[kind] = list(existing.values())
                out.setdefault("meta", {})["result_count"] = len(merged)
                out["meta"]["request_count"] = len(req_out.get("data") or [])
            else:
                out.setdefault("meta", {})["request_inbox_error"] = str(req_res.get("error"))[:200]
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("untrusted inbox merge failed: %s", e)
            out.setdefault("meta", {})["request_inbox_error"] = str(e)

    if xchat_user_id:
        try:
            from app.xchat.events import read_xchat_events
            from app.xchat.bridge import XChatAuthError
            xrows = await read_xchat_events(
                tok,
                xchat_user_id,
                since_ts=xchat_since_ms,
                include_outbound=bool(xchat_include_outbound),
                include_reactions=bool(xchat_include_reactions),
                include_read_receipts=bool(xchat_include_read_receipts),
            )
        except XChatAuthError as e:
            return JSONResponse(
                status_code=401,
                content={
                    "errors": [{
                        "title": "Unauthorized",
                        "detail": f"XChat bridge: {e}",
                        "type": "unauthorized",
                        "status": 401,
                    }]
                },
            )
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning("xchat merge failed: %s", e)
            out.setdefault("meta", {})["xchat_error"] = str(e)
            xrows = []
        if xrows:
            seen = {e.get("id") for e in out.get("data") or []}
            merged = list(out.get("data") or [])
            for r in xrows:
                if r["id"] in seen:
                    continue
                merged.append(r)
            out["data"] = merged
            out.setdefault("meta", {})["result_count"] = len(merged)
            out["meta"]["xchat_count"] = len(xrows)

    return JSONResponse(status_code=200, content=out)


@router.delete("/2/dm_events/{event_id}")
async def v2_dm_event_delete(
    event_id: str = PathParam(...),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    DELETE /2/dm_events/{event_id} — hapus message.
    Backend: REST 1.1 dm/destroy.json
    """
    tok = extract_bearer(authorization, auth_token)
    result = await dm_call(
        "dm/destroy.json",
        tok,
        method="POST",
        data={"id": event_id, "request_id": secrets.token_hex(16)},
        with_dm_defaults=False,
    )
    if raw:
        return wrap(result)
    if result["status"] == "ok":
        return JSONResponse(status_code=200, content={"data": {"deleted": True, "dm_event_id": event_id}})
    return write_finalize(result, raw=False)


@router.get("/2/dm_events/{event_id}")
async def v2_dm_event(
    event_id: str = PathParam(...),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_events/{event_id} — REST 1.1 tidak punya GET single event.
    Workaround: scan inbox lalu filter by id.
    """
    tok = extract_bearer(authorization, auth_token)
    result = await dm_call("dm/user_updates.json", tok, method="GET", params={"count": "100"})
    if raw:
        return wrap(result)
    if result["status"] != "ok":
        return write_finalize(result, raw=False)
    formatted = format_dm_events(result.get("data") or {})
    for ev in formatted.get("data", []):
        if ev.get("id") == event_id:
            return JSONResponse(status_code=200, content={"data": ev})
    return JSONResponse(
        status_code=404,
        content=format_error("Not Found", f"dm_event {event_id} not found in inbox", "not_found", 404),
    )


@router.post("/2/users/{user_id}/dm/block")
async def v2_dm_block(
    user_id: str = PathParam(...),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    POST /2/users/{user_id}/dm/block — block dari menerima DM.
    Backend: REST 1.1 dm/conversation/disable.json (action=block).
    """
    tok = extract_bearer(authorization, auth_token)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )
    conv_id = dm_conv_id_for(me, user_id)
    result = await dm_call(
        "dm/conversation/disable.json",
        tok,
        method="POST",
        data={"conversation_id": conv_id, "request_id": secrets.token_hex(16)},
        with_dm_defaults=False,
    )
    if raw:
        return wrap(result)
    if result["status"] == "ok":
        return JSONResponse(status_code=200, content={"data": {"blocking": True, "user_id": user_id}})
    return write_finalize(result, raw=False)


@router.post("/2/users/{user_id}/dm/unblock")
async def v2_dm_unblock(
    user_id: str = PathParam(...),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    POST /2/users/{user_id}/dm/unblock — unblock DM.
    Backend: REST 1.1 dm/conversation/accept.json
    """
    tok = extract_bearer(authorization, auth_token)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )
    conv_id = dm_conv_id_for(me, user_id)
    result = await dm_call(
        "dm/conversation/accept.json",
        tok,
        method="POST",
        data={"conversation_id": conv_id, "request_id": secrets.token_hex(16)},
        with_dm_defaults=False,
    )
    if raw:
        return wrap(result)
    if result["status"] == "ok":
        return JSONResponse(status_code=200, content={"data": {"blocking": False, "user_id": user_id}})
    return write_finalize(result, raw=False)

