"""Playwright-based resolvers for endpoints yang tidak dapat di-handle httpx.

X anti-bot di-block direct request ke beberapa GraphQL op (UserByRestId,
SearchTimeline, dll). Pakai Playwright headless browser untuk render halaman
publik + intercept network response.
"""

from __future__ import annotations

import contextvars
from typing import Any, Optional

from playwright_search import fetch_via_browser

from .clients import graphql_call
from .config import redact_proxy_creds

_LAST_RESOLVE_SCREEN_NAME_ERR: contextvars.ContextVar[Optional[dict[str, Any]]] = contextvars.ContextVar(
    "xapi_last_resolve_screen_name_err", default=None
)


def reset_last_resolve_screen_name_err() -> None:
    _LAST_RESOLVE_SCREEN_NAME_ERR.set(None)


def pop_last_resolve_screen_name_err() -> Optional[dict[str, Any]]:
    err = _LAST_RESOLVE_SCREEN_NAME_ERR.get()
    _LAST_RESOLVE_SCREEN_NAME_ERR.set(None)
    return err


async def resolve_screen_name(user_id: str, auth_token: str) -> Optional[str]:
    """Lookup screen_name dari user_id via Playwright (UserByRestId/UserByScreenName)."""
    _LAST_RESOLVE_SCREEN_NAME_ERR.set(None)
    try:
        pw = await fetch_via_browser(
            auth_token=auth_token,
            navigate_url=f"https://x.com/i/user/{user_id}",
            match_path=["/UserByRestId", "/UserByScreenName"],
            timeout=15.0,
        )
        if pw.get("status") != "ok":
            _LAST_RESOLVE_SCREEN_NAME_ERR.set({
                "status": pw.get("status") or "error",
                "http_status": pw.get("http_status") or 502,
                "error": pw.get("error"),
                "data": None,
            })
            return None
        u = (pw.get("data") or {}).get("data", {}).get("user", {}).get("result", {})
        return (
            (u.get("core") or {}).get("screen_name")
            or (u.get("legacy") or {}).get("screen_name")
        )
    except Exception as exc:  # noqa: BLE001
        _LAST_RESOLVE_SCREEN_NAME_ERR.set({
            "status": "error",
            "http_status": 502,
            "error": redact_proxy_creds(f"{type(exc).__name__}: {exc}"),
            "data": None,
        })
        return None


async def tweet_author_handle(tweet_id: str, auth_token: str) -> Optional[str]:
    """Resolve author screen_name dari tweet_id via TweetResultByRestId."""
    try:
        result = await graphql_call(
            "TweetResultByRestId",
            {
                "tweetId": tweet_id,
                "withCommunity": False,
                "includePromotedContent": False,
                "withVoice": False,
            },
            auth_token,
        )
        if result["status"] != "ok":
            return None
        tw = (result.get("data") or {}).get("data", {}).get("tweetResult", {}).get("result", {})
        if tw.get("__typename") == "TweetWithVisibilityResults":
            tw = tw.get("tweet", {}) or {}
        core = (tw.get("core") or {}).get("user_results", {}).get("result", {})
        return (
            (core.get("core") or {}).get("screen_name")
            or (core.get("legacy") or {}).get("screen_name")
        )
    except Exception:  # noqa: BLE001
        return None
