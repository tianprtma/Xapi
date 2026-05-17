"""Router for `/` (root) and infrastructure endpoints (login, search, admin stats)."""

from __future__ import annotations

import inspect
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from playwright_search import search_via_browser
from session_cache import SessionStore
from tid_provider import TIDProvider

from ..auth import login_with_auth_token
from ..client_pool import ClientPool
from ..config import ADMIN_TOKEN, SearchType
from ..response_cache import ResponseCache


router = APIRouter(tags=["Infra"])


class SearchRequest(BaseModel):
    auth_token: str = Field(..., min_length=10, description="X auth_token cookie")
    q: str = Field(..., min_length=1, description="Keyword pencarian")
    type: SearchType = Field("Latest", description="Latest | Top | People | Media")


def _require_admin(x_admin_token: Optional[str]) -> None:
    """Reject kalau ADMIN_TOKEN env tidak set, atau header tidak match.

    Pakai constant-time compare untuk avoid timing side-channel.
    """
    import secrets as _secrets
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=404,
            detail="Not Found",
        )
    if not x_admin_token or not _secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )


@router.get("/info")
async def info() -> dict[str, Any]:
    """Service info — minimal metadata, no route inventory leak.

    Endpoint moved from `/` ke `/info` karena root sekarang serve docs-ui static.
    """
    from main import app  # type: ignore[import]

    return {
        "service": app.title,
        "version": app.version,
        "docs": "/docs",
        "reference": "/",
    }


@router.get("/login")
async def login(
    authorization: Optional[str] = Header(None),
    auth_token: Optional[str] = Query(None, min_length=10, description="X auth_token cookie value (DEPRECATED in query)"),
) -> JSONResponse:
    """Validate auth_token + return profile + session info.

    Token dapat di-pass via:
        - `Authorization: Bearer <auth_token>` header (preferred)
        - `?auth_token=` query (DEPRECATED — token bocor di access log)

    Set env `ALLOW_QUERY_AUTH=0` untuk reject query mode di prod.
    """
    from ..auth import extract_bearer
    tok = extract_bearer(authorization, auth_token)
    try:
        result = await login_with_auth_token(tok)
    except httpx.HTTPError:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "error": "Upstream request failed"},
        )
    code = 200 if result["status"] == "valid" else 401
    return JSONResponse(status_code=code, content=result)


# ──────────────────────────── Admin stats (locked behind ADMIN_TOKEN) ────────────────────────────


@router.get("/admin/stats", include_in_schema=False)
async def admin_stats(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """Combined infra stats. Requires `X-Admin-Token` header matching `ADMIN_TOKEN` env."""
    _require_admin(x_admin_token)
    from main import app  # type: ignore[import]

    routes_summary: dict[str, list[str]] = {"implemented": [], "stub_501": []}
    for r in app.routes:
        if not hasattr(r, "methods") or not r.path.startswith("/2/"):
            continue
        try:
            src = inspect.getsource(r.endpoint)
        except (OSError, TypeError):
            src = ""
        bucket = "stub_501" if "stub_501(" in src else "implemented"
        for m in r.methods:
            if m == "HEAD":
                continue
            routes_summary[bucket].append(f"{m} {r.path}")

    return {
        "session_cache": await SessionStore.get().stats(),
        "tid_provider": await TIDProvider.get().stats(),
        "client_pool": await ClientPool.get().stats(),
        "response_cache": await ResponseCache.get().stats(),
        "routes": {
            "v2_total": len(routes_summary["implemented"]) + len(routes_summary["stub_501"]),
            "v2_implemented": len(routes_summary["implemented"]),
            "v2_stub_501": len(routes_summary["stub_501"]),
            "implemented_paths": sorted(routes_summary["implemented"]),
            "stub_paths": sorted(routes_summary["stub_501"]),
        },
    }


@router.post("/search")
async def search(req: SearchRequest) -> JSONResponse:
    """Search tweets/users via Playwright headless browser (~3-6s).

    httpx engine sudah di-deprecate karena X selalu block direct SearchTimeline call.
    """
    try:
        pw_result = await search_via_browser(
            auth_token=req.auth_token,
            q=req.q,
            search_type=req.type,
        )
        # NOTE: pw_result.cookies sengaja TIDAK di-include di response — itu
        # cookie X user (auth_token, ct0, twid, etc) yang kalau bocor =
        # full account compromise. captured_url juga di-strip karena bisa
        # mengandung query params dengan token.
        result = {
            "engine": "playwright",
            "status": pw_result["status"],
            "http_status": pw_result.get("http_status", 200),
            "query": {"q": req.q, "type": req.type},
            "data": pw_result.get("data"),
            "error": pw_result.get("error"),
        }
    except httpx.HTTPError:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "error": "Upstream request failed"},
        )
    except Exception as e:  # noqa: BLE001
        # Log internal exception, return generic message ke client.
        import logging
        logging.getLogger("xapi").exception("search failed: %s", type(e).__name__)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": "Internal Server Error"},
        )

    code_map = {"ok": 200, "invalid": 401, "error": 502}
    return JSONResponse(status_code=code_map.get(result["status"], 500), content=result)
