"""Auto-generated router module for the Direct Messages resource family.

Routes were mechanically extracted from main.py by build_routers.py — when
adding new endpoints, add them directly to this file and import the router
in main.py via `app.include_router`.
"""

from __future__ import annotations

import secrets
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Path as PathParam, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from formatter import (
    format_birdwatch_batsignal,
    format_birdwatch_note_result,
    format_birdwatch_notes_slice,
    format_bookmark_folders,
    format_community,
    format_dm_conversations,
    format_dm_events,
    format_dm_send_result,
    format_error,
    format_public_keys,
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
)
from ..playwright_helpers import resolve_screen_name, tweet_author_handle
from ..responses import finalize, stub_501, wrap, write_finalize
from ..xchat_e2ee import (
    get_cached_e2ee_media,
    resolve_dm_pin,
    send_xchat_dm_via_browser,
    unlock_and_read_xchat_conversation,
    unlock_and_read_xchat_inbox,
)


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


@router.post("/2/chat/conversations/group")
async def v2_chat_group_create() -> JSONResponse:
    return stub_501(feature="chat_group_create", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/group/initialize")
async def v2_chat_group_init() -> JSONResponse:
    return stub_501(feature="chat_group_init", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/keys")
async def v2_chat_keys(conversation_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
    return stub_501(feature="chat_keys", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/members")
async def v2_chat_members(conversation_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
    return stub_501(feature="chat_members", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/messages")
async def v2_chat_messages(
    conversation_id: str = PathParam(..., pattern=r"^\d+([:-]\d+)*$"),
    body: Optional[DMSendBody] = None,
    dm_pin: Optional[str] = Query(None, description="Opsional 4-8 digit PIN XChat E2EE"),
    x_dm_pin: Optional[str] = Header(None, alias="X-DM-Pin"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    if body is None:
        return stub_501(feature="chat_messages", reason=OAUTH2_USER_CTX_REASON)
    tok = extract_bearer(authorization, auth_token)
    pin = resolve_dm_pin(dm_pin, x_dm_pin)
    me = await resolve_me_id(tok)
    norm_conv_id = conversation_id.replace(":", "-")
    if me:
        media_id = body.media_id or ((body.attachments[0] or {}).get("media_id") if body.attachments else None)
        payload = build_dm_new2_payload(
            me=me,
            conv_id=norm_conv_id,
            recipient_ids=None,
            text=body.text,
            media_id=media_id,
            reply_to=body.reply_to_dm_event_id,
        )
        result = await dm_call("dm/new2.json", tok, method="POST", json_body=payload, with_dm_defaults=False)
        if result.get("status") == "ok":
            if raw:
                return wrap(result)
            return JSONResponse(status_code=201, content=format_dm_send_result(result.get("data") or {}))
    if pin:
        pw_res = await send_xchat_dm_via_browser(tok, pin, norm_conv_id, body.text)
        if pw_res.get("status") == "ok":
            return JSONResponse(status_code=201, content={"data": pw_res.get("data")})
    return stub_501(feature="chat_messages", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/read")
async def v2_chat_read(conversation_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
    return stub_501(feature="chat_read", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/conversations/{conversation_id}/typing")
async def v2_chat_typing(conversation_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
    return stub_501(feature="chat_typing", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/media/upload/finalize")
async def v2_chat_mediafinalize() -> JSONResponse:
    return stub_501(feature="chat_media_finalize", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/media/upload/initialize")
async def v2_chat_media_init() -> JSONResponse:
    return stub_501(feature="chat_media_init", reason=OAUTH2_USER_CTX_REASON)


@router.post("/2/chat/media/upload/{media_id}/append")
async def v2_chat_media_append(media_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
    return stub_501(feature="chat_media_append", reason=OAUTH2_USER_CTX_REASON)


def _has_gql_dm_data(result: dict[str, Any]) -> bool:
    """Check if a GraphQL DM response contains non-empty DM data (and no fatal upstream error)."""
    if result.get("status") != "ok":
        return False
    payload = result.get("data")
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if not isinstance(data, dict) or not data:
        return False
    if payload.get("errors") and all(v in (None, {}, []) for v in data.values()):
        return False
    return True


def _format_dm_events_smart(
    payload: dict[str, Any],
    event_types: Optional[str] = None,
    dm_event_fields: Optional[str] = None,
    expansions: Optional[str] = None,
    max_results: Optional[int] = None,
) -> dict[str, Any]:
    """Format DM events and upgrade any GraphQL `_xchat_encrypted` placeholders with REST 1.1 plaintext if present."""
    formatted = format_dm_events(
        payload,
        event_types=event_types,
        dm_event_fields=dm_event_fields,
        expansions=expansions,
        max_results=None,
    )
    if not isinstance(payload, dict):
        return formatted
    rest_only = {
        k: payload[k]
        for k in ("inbox_initial_state", "user_events", "conversation_timeline", "entries", "users", "conversations")
        if k in payload
    }
    if rest_only:
        rest_fmt = format_dm_events(rest_only, event_types=event_types, max_results=None)
        rest_by_id = {str(e["id"]): e for e in (rest_fmt.get("data") or []) if isinstance(e, dict) and e.get("id")}
        if rest_by_id:
            upgraded = []
            for ev in formatted.get("data") or []:
                eid = str(ev.get("id") or "")
                r_ev = rest_by_id.get(eid)
                if r_ev and (
                    ev.get("_xchat_encrypted")
                    or not ev.get("text")
                    or (r_ev.get("_xapi_attachments") and not ev.get("_xapi_attachments"))
                    or (r_ev.get("referenced_tweets") and not ev.get("referenced_tweets"))
                    or (r_ev.get("entities") and not ev.get("entities"))
                ):
                    merged = {**ev, **r_ev}
                    if not r_ev.get("_xchat_encrypted"):
                        merged.pop("_xchat_encrypted", None)
                        merged.pop("encrypted_text", None)
                    upgraded.append(merged)
                else:
                    upgraded.append(ev)
            formatted["data"] = upgraded
        rest_inc = rest_fmt.get("includes") or {}
        if isinstance(rest_inc, dict) and rest_inc:
            fmt_inc = formatted.setdefault("includes", {})
            for inc_key, id_field in (("media", "media_key"), ("tweets", "id")):
                if rest_inc.get(inc_key):
                    existing_list = list(fmt_inc.get(inc_key) or [])
                    seen_keys = {str(item.get(id_field)) for item in existing_list if isinstance(item, dict) and item.get(id_field)}
                    for item in rest_inc[inc_key]:
                        if isinstance(item, dict) and str(item.get(id_field)) not in seen_keys:
                            existing_list.append(item)
                            seen_keys.add(str(item.get(id_field)))
                    fmt_inc[inc_key] = existing_list

    events = formatted.get("data") or []
    events.sort(
        key=lambda x: (str(x.get("created_at") or ""), int(x["id"]) if str(x.get("id", "")).isdigit() else 0),
        reverse=True,
    )
    if max_results and max_results > 0 and len(events) > max_results:
        events = events[:max_results]
        if events and events[-1].get("id"):
            formatted.setdefault("meta", {})["next_token"] = str(events[-1]["id"])
    formatted["data"] = events
    formatted.setdefault("meta", {})["result_count"] = len(events)
    return formatted


def _format_dm_conversations_smart(
    payload: dict[str, Any],
    max_results: Optional[int] = None,
) -> dict[str, Any]:
    """Format DM conversations using _format_dm_events_smart (upgrading GraphQL encrypted events with REST 1.1 plaintext) and sort newest-first."""
    formatted = _format_dm_events_smart(payload)
    includes = formatted.get("includes") or {}
    convs = includes.get("conversations") or []
    events = formatted.get("data") or []
    users = includes.get("users") or []

    latest_by_conv: dict[str, dict[str, Any]] = {}
    for ev in events:
        cid = ev.get("dm_conversation_id")
        if not cid:
            continue
        existing = latest_by_conv.get(cid)
        if not existing:
            latest_by_conv[cid] = ev
        elif existing.get("event_type") != "MessageCreate" and ev.get("event_type") == "MessageCreate":
            latest_by_conv[cid] = ev

    conv_list: list[dict[str, Any]] = []
    for c in convs:
        c_copy = dict(c)
        cid = c_copy.get("id")
        if cid and cid in latest_by_conv:
            c_copy["last_message_event"] = latest_by_conv[cid]
        conv_list.append(c_copy)

    # Sort conversations newest-first by created_at (ISO 8601 UTC) then Snowflake id
    def _conv_sort_key(c_obj: dict[str, Any]) -> tuple[str, int]:
        lme = c_obj.get("last_message_event") or {}
        eid = str(lme.get("id") or c_obj.get("last_read_event_id") or "")
        return (str(lme.get("created_at") or ""), int(eid) if eid.isdigit() else 0)

    conv_list.sort(key=_conv_sort_key, reverse=True)

    if max_results and max_results > 0 and len(conv_list) > max_results:
        conv_list = conv_list[:max_results]

    out: dict[str, Any] = {
        "data": conv_list,
        "meta": {
            "result_count": len(conv_list),
            **({"next_token": formatted["meta"]["next_token"]} if formatted.get("meta", {}).get("next_token") else {}),
        },
    }
    inc_out: dict[str, Any] = {}
    if users:
        inc_out["users"] = users
    if events:
        inc_out["dm_events"] = events
    if inc_out:
        out["includes"] = inc_out
    return out


async def _enrich_conv_events_with_e2ee(
    formatted: dict[str, Any],
    tok: str,
    pin: Optional[str],
    conv_id: str,
    max_results: int = 50,
) -> dict[str, Any]:
    """If `pin` is available and the latest conversation event is encrypted (or events are empty), unlock via XChat E2EE resolver."""
    if not pin:
        return formatted
    events = formatted.get("data") or []
    # Only invoke Playwright E2EE decryption if there are no events or the LATEST event (events[0]) is encrypted
    latest_is_encrypted = bool(events and isinstance(events[0], dict) and events[0].get("_xchat_encrypted"))
    if events and not latest_is_encrypted:
        return formatted

    me = await resolve_me_id(tok)
    decrypted_events = await unlock_and_read_xchat_conversation(
        auth_token=tok,
        dm_pin=pin,
        conversation_id=conv_id,
        my_user_id=me,
        max_results=max_results,
    )
    if not decrypted_events:
        return formatted

    # If we had no events at all, use decrypted DOM rows directly; otherwise merge aligned MessageCreate events
    if not events:
        new_events = decrypted_events[:max_results]
    else:
        # Both `events` and `decrypted_events` are ordered newest-first; align MessageCreate events by message index
        new_events = []
        msg_idx = 0
        for ev in events:
            is_msg = ev.get("event_type") in (None, "MessageCreate")
            if is_msg:
                if ev.get("_xchat_encrypted") and msg_idx < len(decrypted_events):
                    d_ev = decrypted_events[msg_idx]
                    merged = {**ev, **d_ev, "id": ev.get("id") or d_ev.get("id")}
                    if str(ev.get("sender_id") or "").isdigit():
                        merged["sender_id"] = ev["sender_id"]
                        if me:
                            merged["is_outgoing"] = str(ev["sender_id"]) == str(me)
                    if ev.get("created_at"):
                        merged["created_at"] = ev["created_at"]
                    merged.pop("_xchat_encrypted", None)
                    merged.pop("encrypted_text", None)
                    new_events.append(merged)
                else:
                    new_events.append(ev)
                msg_idx += 1
            else:
                new_events.append(ev)
        # If GraphQL only returned the latest 1 message in conversation_timeline while DOM has older messages, append them
        if msg_idx < len(decrypted_events) and len(new_events) < max_results:
            new_events.extend(decrypted_events[msg_idx : msg_idx + (max_results - len(new_events))])

    formatted["data"] = new_events[:max_results]
    formatted["meta"] = {
        **(formatted.get("meta") or {}),
        "result_count": len(formatted["data"]),
        "xchat_decrypted": True,
    }
    return formatted


@router.get("/2/chat/conversations")
async def v2_chat_conversations(
    pagination_token: Optional[str] = Query(None),
    max_results: int = Query(50, ge=1, le=100),
    mode: str = Query("auto", description="graphql | rest | auto"),
    dm_pin: Optional[str] = Query(None, description="Opsional 4-8 digit PIN XChat E2EE"),
    x_dm_pin: Optional[str] = Header(None, alias="X-DM-Pin"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/chat/conversations — ambil daftar percakapan DM / XChat via GraphQL + REST 1.1 (+ E2EE PIN fallback).
    """
    tok = extract_bearer(authorization, auth_token)
    pin = resolve_dm_pin(dm_pin, x_dm_pin)
    result: dict[str, Any] = {}

    if mode.lower() in ("graphql", "auto"):
        if pagination_token:
            result = await graphql_call(
                "GetInboxPageRequestQuery",
                {"continue_cursor": {"cursor_id": pagination_token}, "count": max_results},
                tok,
            )
        else:
            result = await graphql_call(
                "GetInitialXChatPageQuery",
                {"count": max_results},
                tok,
            )
            if not _has_gql_dm_data(result):
                result = await graphql_call(
                    "GetInboxPageRequestQuery",
                    {"count": max_results},
                    tok,
                )

    if mode.lower() == "rest" or (mode.lower() == "auto"):
        params: dict[str, Any] = {}
        if pagination_token:
            params["cursor"] = pagination_token
        rest_res = await dm_call("dm/user_updates.json", tok, params=params)
        if rest_res.get("status") == "ok":
            if _has_gql_dm_data(result) and isinstance(result.get("data"), dict) and isinstance(rest_res.get("data"), dict):
                result = {**result, "data": {**rest_res["data"], **result["data"]}}
            else:
                result = rest_res
        elif not result:
            result = rest_res

    if raw:
        return wrap(result)

    formatted = _format_dm_conversations_smart(result.get("data") or {}, max_results=max_results)
    convs = formatted.get("data") or []
    needs_e2ee = pin and (
        not convs
        or any(((c.get("last_message_event") or {}).get("_xchat_encrypted")) for c in convs if isinstance(c, dict))
    )
    if needs_e2ee and pin:
        me = await resolve_me_id(tok)
        inbox_items = await unlock_and_read_xchat_inbox(tok, pin, my_user_id=me, max_results=max_results)
        if inbox_items:
            by_cid = {item["id"]: item for item in inbox_items if item.get("id")}
            merged_convs = []
            seen_cids = set()
            for c in convs:
                cid = str(c.get("id") or "").replace(":", "-")
                seen_cids.add(cid)
                item = by_cid.get(cid)
                if item:
                    non_null_item = {k: v for k, v in item.items() if v is not None}
                    # Preserve non-intent profile_href if c already has one
                    if c.get("profile_href") and str(item.get("profile_href") or "").startswith("/intent/user"):
                        non_null_item.pop("profile_href", None)
                    c = {**c, **non_null_item}
                    lme = dict(c.get("last_message_event") or {})
                    if (lme.get("_xchat_encrypted") or not lme.get("text")) and item.get("preview_text"):
                        lme["id"] = lme.get("id") or cid
                        lme["dm_conversation_id"] = lme.get("dm_conversation_id") or cid
                        lme["text"] = item["preview_text"]
                        lme.pop("_xchat_encrypted", None)
                        lme["_xchat_decrypted"] = True
                        c["last_message_event"] = lme
                merged_convs.append(c)
            for cid, item in by_cid.items():
                if cid not in seen_cids:
                    merged_convs.append(
                        {
                            "id": cid,
                            "type": "OneToOne",
                            "participant_ids": cid.split("-") if "-" in cid else [],
                            **item,
                            "last_message_event": {
                                "id": cid,
                                "dm_conversation_id": cid,
                                "text": item.get("preview_text"),
                                "_xchat_decrypted": True,
                            },
                        }
                    )
            formatted["data"] = merged_convs[:max_results]
            formatted["meta"] = {**(formatted.get("meta") or {}), "result_count": len(formatted["data"])}

    return JSONResponse(status_code=200, content=formatted)


@router.get("/2/chat/conversations/{conversation_id}/messages")
@router.get("/2/chat/conversations/{conversation_id}/events")
async def v2_chat_conversation_messages(
    conversation_id: str = PathParam(..., pattern=r"^\d+([:-]\d+)*$"),
    pagination_token: Optional[str] = Query(None),
    max_results: int = Query(50, ge=1, le=100),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/chat/conversations/{conversation_id}/messages (dan alias `/events`) — ambil pesan dalam percakapan XChat/DM via GraphQL.
    Backend: GraphQL `GetConversationPageQuery` / `GetMessageEventsPageQuery`.
    """
    tok = extract_bearer(authorization, auth_token)
    conv_id = conversation_id.replace("-", ":")
    variables: dict[str, Any] = {"conversationId": conv_id, "conversation_id": conv_id, "count": max_results}
    if pagination_token:
        variables["cursor"] = pagination_token

    result = await graphql_call("GetConversationPageQuery", variables, tok)
    if not _has_gql_dm_data(result):
        result = await graphql_call("GetMessageEventsPageQuery", variables, tok)

    return finalize(result, lambda d: _format_dm_events_smart(d, max_results=max_results), bool(raw))


@router.get("/2/chat/requests")
async def v2_chat_requests(
    pagination_token: Optional[str] = Query(None),
    max_results: int = Query(50, ge=1, le=100),
    include_low_quality: int = Query(1, description="1 = sertakan low quality / spam requests"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/chat/requests — ambil daftar message requests (untrusted & low-quality inbox) via GraphQL + REST 1.1.
    Backend: GraphQL `GetMessageRequestsPageQuery` + REST 1.1 `dm/inbox_timeline/untrusted.json`
    (& `dm/inbox_timeline/untrusted_low_quality.json`).
    """
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"count": max_results}
    if pagination_token:
        variables["cursor"] = pagination_token

    result = await graphql_call("GetMessageRequestsPageQuery", variables, tok)

    # Also query REST 1.1 untrusted & untrusted_low_quality timelines so plaintext requests are included
    params: dict[str, Any] = {"max_id": pagination_token} if pagination_token else {}
    rest_res = await dm_call("dm/inbox_timeline/untrusted.json", tok, params=params)
    if rest_res.get("status") == "ok" and include_low_quality and not pagination_token:
        lq_res = await dm_call("dm/inbox_timeline/untrusted_low_quality.json", tok)
        if lq_res.get("status") == "ok":
            rest_data = dict(rest_res.get("data") or {})
            base_tl = dict(rest_data.get("inbox_timeline") or {})
            lq_tl = (lq_res.get("data") or {}).get("inbox_timeline") or {}
            if isinstance(lq_tl, dict):
                base_tl["entries"] = list(base_tl.get("entries") or []) + list(lq_tl.get("entries") or [])
                base_tl["users"] = {**(base_tl.get("users") or {}), **(lq_tl.get("users") or {})}
                base_tl["conversations"] = {**(base_tl.get("conversations") or {}), **(lq_tl.get("conversations") or {})}
                rest_data["inbox_timeline"] = base_tl
                rest_res = {**rest_res, "data": rest_data}

    if rest_res.get("status") == "ok":
        rest_tl = (rest_res.get("data") or {}).get("inbox_timeline") or {}
        if _has_gql_dm_data(result) and isinstance(result.get("data"), dict) and isinstance(rest_tl, dict):
            result = {**result, "data": {"inbox_initial_state": rest_tl, **result["data"]}}
        elif isinstance(rest_tl, dict) and rest_tl:
            result = {**rest_res, "data": {"inbox_initial_state": rest_tl}}
        elif not _has_gql_dm_data(result):
            result = rest_res

    return finalize(result, lambda d: _format_dm_events_smart(d, max_results=max_results), bool(raw))


@router.get("/2/chat/permissions")
async def v2_chat_permissions(
    recipient_ids: Optional[str] = Query(None, description="Comma-separated user IDs"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/chat/permissions — cek izin DM / Audio-Video call via GraphQL `DmAvPermissionsQuery`.
    """
    tok = extract_bearer(authorization, auth_token)
    ids = [x.strip() for x in (recipient_ids or "").split(",") if x.strip()]
    variables: dict[str, Any] = {"user_ids": ids, "recipient_ids": ids} if ids else {}
    result = await graphql_call("DmAvPermissionsQuery", variables, tok)
    return write_finalize(result, bool(raw))


@router.get("/2/chat/public_keys")
async def v2_chat_public_keys(
    ids: str = Query(..., description="Comma-separated user rest_ids"),
    include_juicebox_tokens: bool = Query(True),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/chat/public_keys — ambil public keys enkripsi XChat user via GraphQL `GetPublicKeys`.
    """
    tok = extract_bearer(authorization, auth_token)
    id_list = [x.strip() for x in ids.split(",") if x.strip()]
    if not id_list:
        return JSONResponse(
            status_code=400,
            content=format_error("Bad Request", "Parameter 'ids' wajib diisi", "bad_request", 400),
        )
    variables = {"ids": id_list, "include_juicebox_tokens": include_juicebox_tokens}
    result = await graphql_call("GetPublicKeys", variables, tok)
    return finalize(result, format_public_keys, bool(raw))


@router.get("/2/dm_events")
async def v2_dm_events(
    max_results: int = Query(50, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None, description="Comma-separated: MessageCreate,ParticipantsJoin,ParticipantsLeave"),
    dm_event_fields: Optional[str] = Query(None, alias="dm_event.fields"),
    expansions: Optional[str] = Query(None),
    media_fields: Optional[str] = Query(None, alias="media.fields"),
    user_fields: Optional[str] = Query(None, alias="user.fields"),
    tweet_fields: Optional[str] = Query(None, alias="tweet.fields"),
    include_requests: int = Query(1, description="1 = sertakan message requests (untrusted)"),
    mode: str = Query("auto", description="graphql | rest | auto"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_events — ambil daftar DM events terbaru milik user (official X API v2 shape).
    Backend: GraphQL `GetInitialXChatPageQuery` / `GetInboxPageRequestQuery` (+ `GetMessageRequestsPageQuery`
    bila `include_requests=1`), dengan fallback/merge ke REST 1.1 `dm/user_updates.json`.
    """
    tok = extract_bearer(authorization, auth_token)
    result: dict[str, Any] = {}

    if mode.lower() in ("graphql", "auto"):
        if pagination_token:
            result = await graphql_call(
                "GetInboxPageRequestQuery",
                {"continue_cursor": {"cursor_id": pagination_token}, "count": max_results},
                tok,
            )
        else:
            result = await graphql_call(
                "GetInitialXChatPageQuery",
                {"count": max_results},
                tok,
            )
            if not _has_gql_dm_data(result):
                result = await graphql_call(
                    "GetInboxPageRequestQuery",
                    {"count": max_results},
                    tok,
                )

        if include_requests and _has_gql_dm_data(result):
            req_res = await graphql_call(
                "GetMessageRequestsPageQuery",
                {"count": max_results},
                tok,
            )
            if _has_gql_dm_data(req_res):
                base_outer = result.get("data")
                base_data = base_outer.get("data") if isinstance(base_outer, dict) else None
                req_data = (req_res.get("data") or {}).get("data")
                if isinstance(base_outer, dict) and isinstance(base_data, dict) and isinstance(req_data, dict):
                    merged_inner = {**req_data, **base_data}
                    result = {**result, "data": {**base_outer, "data": merged_inner}}

    if mode.lower() == "rest" or (mode.lower() == "auto"):
        params: dict[str, Any] = {}
        if pagination_token:
            params["cursor"] = pagination_token
        rest_res = await dm_call("dm/user_updates.json", tok, params=params)
        if rest_res.get("status") == "ok" and include_requests:
            rest_data = dict(rest_res.get("data") or {})
            base_inbox = dict(rest_data.get("inbox_initial_state") or {})
            base_entries = list(base_inbox.get("entries") or [])
            base_users = dict(base_inbox.get("users") or {})
            base_convs = dict(base_inbox.get("conversations") or {})
            untrusted_tl = (base_inbox.get("inbox_timelines") or {}).get("untrusted") or {}
            for tl_path, max_id in [
                ("dm/inbox_timeline/untrusted.json", untrusted_tl.get("min_entry_id")),
                ("dm/inbox_timeline/untrusted_low_quality.json", None),
            ]:
                extra_params: dict[str, Any] = {"max_id": max_id} if max_id else {}
                extra = await dm_call(tl_path, tok, params=extra_params)
                if extra.get("status") != "ok":
                    continue
                tl = (extra.get("data") or {}).get("inbox_timeline") or {}
                if not isinstance(tl, dict):
                    continue
                base_entries.extend(tl.get("entries") or [])
                base_users.update(tl.get("users") or {})
                base_convs.update(tl.get("conversations") or {})
            base_inbox["entries"] = base_entries
            base_inbox["users"] = base_users
            base_inbox["conversations"] = base_convs
            rest_data["inbox_initial_state"] = base_inbox
            rest_res = {**rest_res, "data": rest_data}
        if rest_res.get("status") == "ok":
            if _has_gql_dm_data(result) and isinstance(result.get("data"), dict) and isinstance(rest_res.get("data"), dict):
                # Merge REST 1.1 plaintext inbox_initial_state alongside GraphQL data so format_dm_events gets both!
                result = {**result, "data": {**rest_res["data"], **result["data"]}}
            else:
                result = rest_res
        elif not result:
            result = rest_res

    return finalize(
        result,
        lambda d: _format_dm_events_smart(
            d,
            event_types=event_types,
            dm_event_fields=dm_event_fields,
            expansions=expansions,
            max_results=max_results,
        ),
        bool(raw),
    )


@router.get("/2/dm_events/search")
async def v2_dm_events_search(
    query: str = Query(..., min_length=1, description="Kata kunci pencarian DM"),
    search_type: str = Query("all", description="all | groups | people"),
    max_results: int = Query(20, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_events/search — cari pesan/grup/orang di Direct Messages via GraphQL.
    Backend: GraphQL `DmAllSearchSlice` / `DmGroupSearchSlice` / `DmPeopleSearchSlice`.
    """
    tok = extract_bearer(authorization, auth_token)
    op_map = {
        "all": "DmAllSearchSlice",
        "groups": "DmGroupSearchSlice",
        "group": "DmGroupSearchSlice",
        "people": "DmPeopleSearchSlice",
        "users": "DmPeopleSearchSlice",
    }
    operation = op_map.get(search_type.lower(), "DmAllSearchSlice")
    variables: dict[str, Any] = {
        "query": query,
        "count": max_results,
        "dm_users": True,
        "include_groups": True,
        "include_messages": True,
    }
    if pagination_token:
        variables["cursor"] = pagination_token

    result = await graphql_call(operation, variables, tok)
    return finalize(result, lambda d: _format_dm_events_smart(d, max_results=max_results), bool(raw))


@router.get("/2/dm_events/{event_id}")
async def v2_dm_event_by_id(
    event_id: str = PathParam(..., pattern=r"^\d+$"),
    conversation_id: Optional[str] = Query(None, description="Opsional conversation_id untuk query langsung"),
    mode: str = Query("auto", description="graphql | rest | auto"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_events/{event_id} — detail 1 DM event.
    Backend: GraphQL `GetMessageEventsPageQuery` / `GetInitialXChatPageQuery`,
    dengan fallback scan inbox `dm/user_updates.json`.
    """
    tok = extract_bearer(authorization, auth_token)
    result: dict[str, Any] = {}

    if mode.lower() in ("graphql", "auto"):
        if conversation_id:
            conv_id = conversation_id.replace(":", "-")
            result = await graphql_call(
                "GetMessageEventsPageQuery",
                {"conversation_id": conv_id, "conversationId": conv_id, "count": 50},
                tok,
            )
        if not _has_gql_dm_data(result):
            result = await graphql_call("GetInitialXChatPageQuery", {"count": 50}, tok)

        if _has_gql_dm_data(result):
            if raw:
                return wrap(result)
            formatted = format_dm_events(result.get("data") or {})
            hit = next((e for e in formatted.get("data") or [] if e.get("id") == event_id), None)
            if hit:
                return JSONResponse(
                    status_code=200,
                    content={"data": hit, **({"includes": formatted["includes"]} if "includes" in formatted else {})},
                )

    if mode.lower() in ("rest", "auto"):
        rest_res = await dm_call("dm/user_updates.json", tok)
        if raw and mode.lower() == "rest":
            return wrap(rest_res)
        if rest_res.get("status") == "ok":
            formatted = format_dm_events(rest_res.get("data") or {})
            hit = next((e for e in formatted.get("data") or [] if e.get("id") == event_id), None)
            if hit:
                return JSONResponse(
                    status_code=200,
                    content={"data": hit, **({"includes": formatted["includes"]} if "includes" in formatted else {})},
                )
            result = rest_res

    if raw and result:
        return wrap(result)
    if result and result.get("status") not in ("ok", "valid"):
        return finalize(result, format_dm_events, False)
    return JSONResponse(
        status_code=404,
        content=format_error("Not Found", f"dm_event {event_id} not in recent inbox", "not_found", 404),
    )


@router.get("/2/dm_conversations/{conversation_id}/dm_events")
async def v2_dm_conv_events(
    conversation_id: str = PathParam(..., pattern=r"^\d+([:-]\d+)*$"),
    max_results: int = Query(50, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None, description="Comma-separated: MessageCreate,ParticipantsJoin,ParticipantsLeave"),
    dm_event_fields: Optional[str] = Query(None, alias="dm_event.fields"),
    expansions: Optional[str] = Query(None),
    media_fields: Optional[str] = Query(None, alias="media.fields"),
    user_fields: Optional[str] = Query(None, alias="user.fields"),
    tweet_fields: Optional[str] = Query(None, alias="tweet.fields"),
    mode: str = Query("auto", description="graphql | rest | auto"),
    dm_pin: Optional[str] = Query(None, description="Opsional 4-8 digit PIN XChat E2EE"),
    x_dm_pin: Optional[str] = Header(None, alias="X-DM-Pin"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_conversations/{conversation_id}/dm_events — semua event dalam 1 conversation.
    Backend: GraphQL `GetConversationPageQuery` / `GetMessageEventsPageQuery`,
    dengan fallback ke REST 1.1 `dm/conversation/{conv_id}.json` + XChat E2EE `dm_pin` resolver.
    """
    tok = extract_bearer(authorization, auth_token)
    pin = resolve_dm_pin(dm_pin, x_dm_pin)
    conv_id = conversation_id.replace(":", "-")
    gql_conv_id = conv_id.replace("-", ":")
    result: dict[str, Any] = {}

    if mode.lower() in ("graphql", "auto"):
        variables: dict[str, Any] = {
            "conversationId": gql_conv_id,
            "conversation_id": gql_conv_id,
            "count": max_results,
        }
        if pagination_token:
            variables["cursor"] = pagination_token
        result = await graphql_call("GetConversationPageQuery", variables, tok)
        if not _has_gql_dm_data(result):
            result = await graphql_call("GetMessageEventsPageQuery", variables, tok)

    if mode.lower() == "rest" or (mode.lower() == "auto"):
        params: dict[str, Any] = {"count": max_results}
        if pagination_token:
            params["max_id"] = pagination_token
        rest_res = await dm_call(f"dm/conversation/{conv_id}.json", tok, params=params)
        if rest_res.get("status") == "ok":
            if _has_gql_dm_data(result) and isinstance(result.get("data"), dict) and isinstance(rest_res.get("data"), dict):
                result = {**result, "data": {**rest_res["data"], **result["data"]}}
            else:
                result = rest_res
        elif not result:
            result = rest_res

    if raw:
        return wrap(result)

    formatted = _format_dm_events_smart(
        result.get("data") or {},
        event_types=event_types,
        dm_event_fields=dm_event_fields,
        expansions=expansions,
        max_results=max_results,
    )
    if pin:
        formatted = await _enrich_conv_events_with_e2ee(formatted, tok, pin, conv_id, max_results=max_results)
    return JSONResponse(status_code=200, content=formatted)


@router.get("/2/dm_conversations/with/{participant_id}/dm_events")
async def v2_dm_with_user_events(
    participant_id: str = PathParam(..., pattern=r"^\d+$"),
    max_results: int = Query(50, ge=1, le=100),
    pagination_token: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None, description="Comma-separated: MessageCreate,ParticipantsJoin,ParticipantsLeave"),
    dm_event_fields: Optional[str] = Query(None, alias="dm_event.fields"),
    expansions: Optional[str] = Query(None),
    media_fields: Optional[str] = Query(None, alias="media.fields"),
    user_fields: Optional[str] = Query(None, alias="user.fields"),
    tweet_fields: Optional[str] = Query(None, alias="tweet.fields"),
    mode: str = Query("auto", description="graphql | rest | auto"),
    dm_pin: Optional[str] = Query(None, description="Opsional 4-8 digit PIN XChat E2EE"),
    x_dm_pin: Optional[str] = Header(None, alias="X-DM-Pin"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_conversations/with/{participant_id}/dm_events — 1-on-1 DM history dengan user tertentu.
    Resolve `me` → hitung `conv_id = "{min(me, them)}-{max(me, them)}"` → ambil via GraphQL / REST / E2EE.
    """
    tok = extract_bearer(authorization, auth_token)
    pin = resolve_dm_pin(dm_pin, x_dm_pin)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "Cannot resolve owner user_id from auth_token", "unauthorized", 401),
        )
    conv_id = dm_conv_id_for(me, participant_id)
    gql_conv_id = conv_id.replace("-", ":")
    result: dict[str, Any] = {}

    if mode.lower() in ("graphql", "auto"):
        variables: dict[str, Any] = {
            "conversationId": gql_conv_id,
            "conversation_id": gql_conv_id,
            "count": max_results,
        }
        if pagination_token:
            variables["cursor"] = pagination_token
        result = await graphql_call("GetConversationPageQuery", variables, tok)
        if not _has_gql_dm_data(result):
            result = await graphql_call("GetMessageEventsPageQuery", variables, tok)

    if mode.lower() == "rest" or (mode.lower() == "auto"):
        params: dict[str, Any] = {"count": max_results}
        if pagination_token:
            params["max_id"] = pagination_token
        rest_res = await dm_call(f"dm/conversation/{conv_id}.json", tok, params=params)
        if rest_res.get("status") == "ok":
            if _has_gql_dm_data(result) and isinstance(result.get("data"), dict) and isinstance(rest_res.get("data"), dict):
                result = {**result, "data": {**rest_res["data"], **result["data"]}}
            else:
                result = rest_res
        elif not result:
            result = rest_res

    if raw:
        return wrap(result)

    formatted = _format_dm_events_smart(
        result.get("data") or {},
        event_types=event_types,
        dm_event_fields=dm_event_fields,
        expansions=expansions,
        max_results=max_results,
    )
    if pin:
        formatted = await _enrich_conv_events_with_e2ee(formatted, tok, pin, conv_id, max_results=max_results)
    return JSONResponse(status_code=200, content=formatted)


@router.get("/2/dm_conversations/media/{dm_id}/{media_id}/{resource_id}", response_model=None)
@router.get("/2/dm_conversations/media/{dm_id}/{media_id:path}/{resource_id}", response_model=None)
async def v2_dm_media_proxy(
    dm_id: str = PathParam(..., pattern=r"^(\d+(-\d+)*|xchat)$"),
    media_id: str = PathParam(..., pattern=r"^[A-Za-z0-9_/-]+$"),
    resource_id: str = PathParam(..., pattern=r"^[A-Za-z0-9._-]+$", description="Filename e.g. Z4k2_BaF.jpg or vid.mp4"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
) -> Response:
    """
    GET /2/dm_conversations/media/{dm_id}/{media_id}/{resource_id} — proxy download binary media DM
    (foto, GIF, video dari `ton.x.com` maupun gambar `blob:` XChat E2EE yang di-cache di memori).
    """
    from ..auth import api_headers
    from ..client_pool import pooled_client

    if ".." in media_id or ".." in resource_id:
        return JSONResponse(
            status_code=400,
            content=format_error("Bad Request", "Invalid media path segment", "bad_request", 400),
        )

    if dm_id == "xchat":
        cached = get_cached_e2ee_media(media_id.strip("/"))
        if not cached:
            return JSONResponse(
                status_code=404,
                content=format_error("Not Found", "Cached XChat E2EE media expired or not found", "not_found", 404),
            )
        raw_bytes, mime = cached
        return Response(content=raw_bytes, media_type=mime)

    tok = extract_bearer(authorization, auth_token)
    url = f"https://ton.x.com/1.1/ton/data/dm/{dm_id}/{media_id.strip('/')}/{resource_id}"
    async with pooled_client(tok) as client:
        ct0, cookies = await warm_session(client, tok)
        for k, v in cookies.items():
            client.cookies.set(k, v, domain=".x.com")
            client.cookies.set(k, v, domain=".twitter.com")
        hdrs = {**api_headers(ct0, tok), "referer": "https://x.com/messages"}
        hdrs.pop("content-type", None)
        resp = await client.get(url, headers=hdrs)
        if resp.status_code != 200:
            return JSONResponse(
                status_code=resp.status_code if resp.status_code in (401, 403, 404) else 502,
                content=format_error("Media Fetch Error", f"Upstream ton.x.com returned {resp.status_code}", "upstream_error", resp.status_code),
            )
        content_type = resp.headers.get("content-type") or "application/octet-stream"
        return Response(content=resp.content, media_type=content_type)


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
        unique_pids = {str(me)} | {str(p) for p in body.participant_ids if p}
        payload["conversation_id"] = "-".join(
            sorted(unique_pids, key=lambda x: (0, x.zfill(30)) if x.isdigit() else (1, x))
        )
    # OneToOne: biarkan recipient_ids auto-create conversation. Mengirim
    # conversation_id untuk conversation yang belum ada ditolak X (code 214).

    result = await dm_call("dm/new2.json", tok, method="POST", json_body=payload, with_dm_defaults=False)
    if raw:
        return wrap(result)
    if result["status"] != "ok":
        return write_finalize(result, raw=False)
    return JSONResponse(status_code=201, content=format_dm_send_result(result.get("data") or {}))


@router.post("/2/dm_conversations/with/{participant_id}/messages")
async def v2_dm_send(
    participant_id: str = PathParam(..., pattern=r"^\d+$"),
    body: DMSendBody = ...,
    dm_pin: Optional[str] = Query(None, description="Opsional 4-8 digit PIN XChat E2EE"),
    x_dm_pin: Optional[str] = Header(None, alias="X-DM-Pin"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    POST /2/dm_conversations/with/{participant_id}/messages — kirim DM 1-1.
    Backend: REST 1.1 dm/new2.json (auto-create conv kalau belum ada), dengan fallback XChat E2EE bila dm_pin tersedia.
    """
    tok = extract_bearer(authorization, auth_token)
    pin = resolve_dm_pin(dm_pin, x_dm_pin)
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
        if pin:
            conv_id = dm_conv_id_for(me, participant_id)
            pw_res = await send_xchat_dm_via_browser(tok, pin, conv_id, body.text)
            if pw_res.get("status") == "ok":
                return JSONResponse(status_code=201, content={"data": pw_res.get("data")})
        return write_finalize(result, raw=False)
    return JSONResponse(status_code=201, content=format_dm_send_result(result.get("data") or {}))


@router.post("/2/dm_conversations/{conversation_id}/messages")
async def v2_dm_send_to_conv(
    # 1-1 atau group conversation id ("<uid1>-<uid2>" atau "<uid1>-<uid2>-<uid3>" atau XChat ":")
    conversation_id: str = PathParam(..., pattern=r"^\d+([:-]\d+)*$"),
    body: DMSendBody = ...,
    dm_pin: Optional[str] = Query(None, description="Opsional 4-8 digit PIN XChat E2EE"),
    x_dm_pin: Optional[str] = Header(None, alias="X-DM-Pin"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    POST /2/dm_conversations/{conversation_id}/messages — kirim ke conv tertentu (1-1 atau group).
    Backend: REST 1.1 dm/new2.json + fallback XChat E2EE bila dm_pin tersedia.
    """
    tok = extract_bearer(authorization, auth_token)
    pin = resolve_dm_pin(dm_pin, x_dm_pin)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )
    media_id = body.media_id
    if not media_id and body.attachments:
        media_id = (body.attachments[0] or {}).get("media_id")
    norm_conv_id = conversation_id.replace(":", "-")
    payload = build_dm_new2_payload(
        me=me,
        conv_id=norm_conv_id,
        recipient_ids=None,
        text=body.text,
        media_id=media_id,
        reply_to=body.reply_to_dm_event_id,
    )
    result = await dm_call("dm/new2.json", tok, method="POST", json_body=payload, with_dm_defaults=False)
    if raw:
        return wrap(result)
    if result["status"] != "ok":
        if pin:
            pw_res = await send_xchat_dm_via_browser(tok, pin, norm_conv_id, body.text)
            if pw_res.get("status") == "ok":
                return JSONResponse(status_code=201, content={"data": pw_res.get("data")})
        return write_finalize(result, raw=False)
    return JSONResponse(status_code=201, content=format_dm_send_result(result.get("data") or {}))


@router.delete("/2/dm_events/{event_id}")
async def v2_dm_event_delete(
    event_id: str = PathParam(..., pattern=r"^\d+$"),
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


@router.post("/2/users/{user_id}/dm/block")
async def v2_dm_block(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
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
        method="GET",
        params={"conversation_id": conv_id, "request_id": secrets.token_hex(16)},
        with_dm_defaults=False,
    )
    # X web sudah memensiunkan disable.json granular (balas 279 "conversation
    # doesn't exist" meski conversation valid) — fallback ke account-level
    # block yang sama dengan route /2/users/{id}/blocking.
    if result["status"] == "error" and result.get("http_status") == 404:
        result = await rest_call("blocks/create.json", tok, data={"user_id": user_id})
        if result["status"] == "ok":
            return JSONResponse(status_code=200, content={"data": {"blocking": True, "user_id": user_id}})
    if raw:
        return wrap(result)
    if result["status"] == "ok":
        return JSONResponse(status_code=200, content={"data": {"blocking": True, "user_id": user_id}})
    return write_finalize(result, raw=False)


@router.post("/2/users/{user_id}/dm/unblock")
async def v2_dm_unblock(
    user_id: str = PathParam(..., pattern=r"^\d+$"),
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
        method="GET",
        params={"conversation_id": conv_id, "request_id": secrets.token_hex(16)},
        with_dm_defaults=False,
    )
    # Mirror fallback dm/block: X memensiunkan endpoint granular — pakai
    # account-level unblock.
    if result["status"] == "error" and result.get("http_status") == 404:
        result = await rest_call("blocks/destroy.json", tok, data={"user_id": user_id})
        if result["status"] == "ok":
            return JSONResponse(status_code=200, content={"data": {"blocking": False, "user_id": user_id}})
    if raw:
        return wrap(result)
    if result["status"] == "ok":
        return JSONResponse(status_code=200, content={"data": {"blocking": False, "user_id": user_id}})
    return write_finalize(result, raw=False)


# ──────────────────────────── Approve / Reject DM Requests ────────────────────────────


async def _accept_dm_conversation(conv_id: str, tok: str, raw: int) -> JSONResponse:
    """Helper internal: approve (accept) message request conversation_id."""
    norm_conv_id = conv_id.replace(":", "-")
    result = await dm_call(
        f"dm/conversation/{norm_conv_id}/accept.json",
        tok,
        method="POST",
        data={"request_id": secrets.token_hex(16)},
        with_dm_defaults=False,
    )
    if result["status"] != "ok" and result.get("http_status") == 404:
        result = await dm_call(
            "dm/conversation/accept.json",
            tok,
            method="POST",
            data={"conversation_id": norm_conv_id, "request_id": secrets.token_hex(16)},
            with_dm_defaults=False,
        )
    if raw:
        return wrap(result)
    if result["status"] == "ok":
        return JSONResponse(
            status_code=200,
            content={"data": {"accepted": True, "trusted": True, "dm_conversation_id": norm_conv_id}},
        )
    return write_finalize(result, raw=False)


async def _delete_dm_conversation(conv_id: str, tok: str, raw: int) -> JSONResponse:
    """Helper internal: reject / delete message request atau percakapan DM."""
    norm_conv_id = conv_id.replace(":", "-")
    result = await dm_call(
        f"dm/conversation/{norm_conv_id}/delete.json",
        tok,
        method="POST",
        data={"last_event_id": "0", "request_id": secrets.token_hex(16)},
        with_dm_defaults=False,
    )
    if raw:
        return wrap(result)
    if result["status"] == "ok":
        return JSONResponse(
            status_code=200,
            content={"data": {"deleted": True, "dm_conversation_id": norm_conv_id}},
        )
    return write_finalize(result, raw=False)


@router.post("/2/dm_conversations/{conversation_id}/accept")
@router.post("/2/chat/requests/{conversation_id}/accept")
async def v2_dm_conv_accept(
    conversation_id: str = PathParam(..., pattern=r"^\d+([:-]\d+)*$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    POST /2/dm_conversations/{conversation_id}/accept (dan alias `/2/chat/requests/{conversation_id}/accept`)
    — Approve / terima DM message request berdasarkan `conversation_id` (memindahkan dari Untrusted ke Primary Inbox).
    Backend: REST 1.1 `POST dm/conversation/{conversation_id}/accept.json`.
    """
    tok = extract_bearer(authorization, auth_token)
    return await _accept_dm_conversation(conversation_id, tok, raw)


@router.post("/2/dm_conversations/with/{participant_id}/accept")
async def v2_dm_with_user_accept(
    participant_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    POST /2/dm_conversations/with/{participant_id}/accept
    — Approve / terima DM message request dari user tertentu (`participant_id`).
    """
    tok = extract_bearer(authorization, auth_token)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )
    conv_id = dm_conv_id_for(me, participant_id)
    return await _accept_dm_conversation(conv_id, tok, raw)


@router.delete("/2/dm_conversations/{conversation_id}")
@router.post("/2/dm_conversations/{conversation_id}/reject")
@router.delete("/2/chat/requests/{conversation_id}")
async def v2_dm_conv_delete(
    conversation_id: str = PathParam(..., pattern=r"^\d+([:-]\d+)*$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    DELETE /2/dm_conversations/{conversation_id} (dan alias `POST /2/dm_conversations/{conversation_id}/reject`,
    `DELETE /2/chat/requests/{conversation_id}`)
    — Reject / hapus DM message request atau keluar dari percakapan DM.
    Backend: REST 1.1 `POST dm/conversation/{conversation_id}/delete.json`.
    """
    tok = extract_bearer(authorization, auth_token)
    return await _delete_dm_conversation(conversation_id, tok, raw)


@router.delete("/2/dm_conversations/with/{participant_id}")
@router.post("/2/dm_conversations/with/{participant_id}/reject")
async def v2_dm_with_user_delete(
    participant_id: str = PathParam(..., pattern=r"^\d+$"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    DELETE /2/dm_conversations/with/{participant_id} (dan alias `POST /2/dm_conversations/with/{participant_id}/reject`)
    — Reject / hapus DM message request atau percakapan 1-on-1 dengan user tertentu (`participant_id`).
    """
    tok = extract_bearer(authorization, auth_token)
    me = await resolve_me_id(tok)
    if not me:
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", "auth_token invalid/expired", "unauthorized", 401),
        )
    conv_id = dm_conv_id_for(me, participant_id)
    return await _delete_dm_conversation(conv_id, tok, raw)
