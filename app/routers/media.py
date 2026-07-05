"""Auto-generated router module for the Media resource family.

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

from ..auth import extract_bearer

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


router = APIRouter(tags=["Media"])


@router.post("/2/media/metadata")
async def v2_media_metadata(
    request: Request,
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
) -> JSONResponse:
    """POST /2/media/metadata — alt_text via media/metadata/create.json (REST 1.1)."""
    tok = extract_bearer(authorization, auth_token)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=400, content=format_error("Bad Request", "invalid JSON", "bad_request", 400))
    result = await rest_call("media/metadata/create.json", tok, json_body=body)
    return write_finalize(result, raw=False)


@router.post("/2/media/upload")
async def v2media_upload(
    request: Request,
    media_type: str = Query(..., description="MIME, contoh: image/jpeg, video/mp4, image/gif"),
    media_category: Optional[str] = Query(
        None,
        description="tweet_image | tweet_video | tweet_gif | dm_image | dm_video (auto kalau kosong)",
    ),
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None),
    raw: int = Query(0),
) -> JSONResponse:
    """Upload media via raw body (bytes mentah)."""
    tok = extract_bearer(authorization, auth_token)
    body = await request.body()
    if not body:
        return JSONResponse(
            status_code=400,
            content=format_error("Bad Request", "request body kosong", "bad_request", 400),
        )

    # Auto kategori dari media_type
    cat = media_category
    if not cat:
        if media_type.startswith("video/"):
            cat = "tweet_video"
        elif media_type == "image/gif":
            cat = "tweet_gif"
        elif media_type.startswith("image/"):
            cat = "tweet_image"

    result = await media_upload(tok, body, media_type=media_type, media_category=cat)

    if raw:
        return wrap(result)

    if result["status"] == "ok":
        d = result.get("data") or {}
        return JSONResponse(
            status_code=200,
            content={
                "data": {
                    "media_id": d.get("media_id_string") or str(d.get("media_id") or ""),
                    "media_key": d.get("media_key"),
                    "size": d.get("size"),
                    "expires_after_secs": d.get("expires_after_secs"),
                    "image": d.get("image"),
                    "video": d.get("video"),
                    "processing_info": d.get("processing_info"),
                }
            },
        )
    if result["status"] == "invalid":
        return JSONResponse(
            status_code=401,
            content=format_error("Unauthorized", str(result.get("error"))[:500], "unauthorized", 401),
        )
    return JSONResponse(
        status_code=result.get("http_status") or 502,
        content=format_error(
            "Upload Failed",
            str(result.get("error"))[:1000],
            "upload_error",
            result.get("http_status") or 502,
        ),
    )


@router.post("/2/media/upload/initialize")
async def v2_media_upload_init() -> JSONResponse:
    return stub_501(
        feature="media_upload_initialize",
        reason="Pakai POST /2/media/upload (one-shot) — chunked init/append/finalize handled internally.",
        suggestion="POST /2/media/upload?media_type=image/jpeg dgn raw body bytes.",
    )


@router.post("/2/media/upload/{media_id}/append")
async def v2_media_upload_append(media_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
    return stub_501(feature="media_upload_append", reason="Lihat /2/media/upload/initialize.")


@router.post("/2/media/upload/{media_id}/finalize")
async def v2_media_uploadfinalize(media_id: str = PathParam(..., pattern=r"^\d+$")) -> JSONResponse:
    return stub_501(feature="media_upload_finalize", reason="Lihat /2/media/upload/initialize.")

