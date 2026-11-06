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
async def v2_chat_messages(conversation_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
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


@router.get("/2/chat/conversations")
async def v2_chat_conversations(
    pagination_token: Optional[str] = Query(None),
    max_results: int = Query(50, ge=1, le=100),
    mode: str = Query("graphql", description="graphql | rest | auto"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/chat/conversations — ambil daftar percakapan DM / XChat via GraphQL.
    Backend: GraphQL `GetInboxPageRequestQuery` (jika ada pagination_token) atau
    `GetInitialXChatPageQuery`, dengan fallback opsional ke REST 1.1 `dm/user_updates.json`.
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

    return finalize(result, lambda d: format_dm_conversations(d, max_results=max_results), bool(raw))


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

    return finalize(result, lambda d: format_dm_events(d, max_results=max_results), bool(raw))


@router.get("/2/chat/requests")
async def v2_chat_requests(
    pagination_token: Optional[str] = Query(None),
    max_results: int = Query(50, ge=1, le=100),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/chat/requests — ambil daftar message requests (untrusted inbox) via GraphQL.
    Backend: GraphQL `GetMessageRequestsPageQuery` dengan fallback ke REST 1.1 `dm/inbox_timeline/untrusted.json`.
    """
    tok = extract_bearer(authorization, auth_token)
    variables: dict[str, Any] = {"count": max_results}
    if pagination_token:
        variables["cursor"] = pagination_token

    result = await graphql_call("GetMessageRequestsPageQuery", variables, tok)
    if not _has_gql_dm_data(result):
        params: dict[str, Any] = {"max_id": pagination_token} if pagination_token else {}
        rest_res = await dm_call("dm/inbox_timeline/untrusted.json", tok, params=params)
        if rest_res.get("status") == "ok":
            result = rest_res

    return finalize(result, lambda d: format_dm_events(d, max_results=max_results), bool(raw))


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
        lambda d: format_dm_events(
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
    return finalize(result, lambda d: format_dm_events(d, max_results=max_results), bool(raw))


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
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_conversations/{conversation_id}/dm_events — semua event dalam 1 conversation.
    Backend: GraphQL `GetConversationPageQuery` / `GetMessageEventsPageQuery`,
    dengan fallback ke REST 1.1 `dm/conversation/{conv_id}.json`.
    """
    tok = extract_bearer(authorization, auth_token)
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

    return finalize(
        result,
        lambda d: format_dm_events(
            d,
            event_types=event_types,
            dm_event_fields=dm_event_fields,
            expansions=expansions,
            max_results=max_results,
        ),
        bool(raw),
    )


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
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """
    GET /2/dm_conversations/with/{participant_id}/dm_events — 1-on-1 DM history dengan user tertentu.
    Resolve `me` → hitung `conv_id = "{min(me, them)}-{max(me, them)}"` → ambil via GraphQL / REST.
    """
    tok = extract_bearer(authorization, auth_token)
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

    return finalize(
        result,
        lambda d: format_dm_events(
            d,
            event_types=event_types,
            dm_event_fields=dm_event_fields,
            expansions=expansions,
            max_results=max_results,
        ),
        bool(raw),
    )


@router.get("/2/dm_conversations/media/{dm_id}/{media_id}/{resource_id}", response_model=None)
async def v2_dm_media_proxy(
    dm_id: str = PathParam(..., pattern=r"^\d+$"),
    media_id: str = PathParam(..., pattern=r"^\d+$"),
    resource_id: str = PathParam(..., description="Filename e.g. Z4k2_BaF.jpg"),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
) -> Response:
    """
    GET /2/dm_conversations/media/{dm_id}/{media_id}/{resource_id} — proxy download binary media DM
    dari `https://ton.x.com/1.1/ton/data/dm/{dm_id}/{media_id}/{resource_id}` menggunakan sesi `auth_token`.
    """
    from ..auth import api_headers
    from ..client_pool import pooled_client

    tok = extract_bearer(authorization, auth_token)
    url = f"https://ton.x.com/1.1/ton/data/dm/{dm_id}/{media_id}/{resource_id}"
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


@router.post("/2/dm_conversations/{conversation_id}/messages")
async def v2_dm_send_to_conv(
    # 1-1 atau group conversation id ("<uid1>-<uid2>" atau "<uid1>-<uid2>-<uid3>" atau XChat ":")
    conversation_id: str = PathParam(..., pattern=r"^\d+([:-]\d+)*$"),
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
