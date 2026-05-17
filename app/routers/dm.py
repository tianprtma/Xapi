"""Auto-generated router module for the Direct Messages resource family.

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

    payload: dict[str, Any] = {
        "conversation_id": None,
        "recipient_ids": body.participant_ids,
        "request_id": secrets.token_hex(16),
        "text": text,
        "cards_platform": "Web-12",
        "include_cards": 1,
        "include_quote_count": True,
        "dm_users": True,
    }
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
) -> JSONResponse:
    """Media binary download — butuh signed URL flow yang tidak ter-mirror clean. Skip dulu."""
    return stub_501(
        feature="dm_media",
        reason="DM media binary download butuh signed URL + ext_media_availability flow yang tidak feasible di-mirror tanpa user-agent strict.",
    )


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
    payload = build_dm_new2_payload(
        me=me,
        conv_id=dm_conv_id_for(me, participant_id),
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
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_events — list semua DM events dari inbox.
    Backend: REST 1.1 dm/user_updates.json (cursor-based polling).
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
    return JSONResponse(status_code=200, content=format_dm_events(result.get("data") or {}))


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

