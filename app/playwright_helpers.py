"""Playwright-based resolvers for endpoints yang tidak dapat di-handle httpx.

X anti-bot di-block direct request ke beberapa GraphQL op (UserByRestId,
SearchTimeline, dll). Pakai Playwright headless browser untuk render halaman
publik + intercept network response.
"""

from __future__ import annotations

from typing import Optional

from playwright_search import fetch_via_browser

from .clients import graphql_call


async def resolve_screen_name(user_id: str, auth_token: str) -> Optional[str]:
    """Lookup screen_name dari user_id via Playwright (UserByRestId/UserByScreenName)."""
    try:
        pw = await fetch_via_browser(
            auth_token=auth_token,
            navigate_url=f"https://x.com/i/user/{user_id}",
            match_path=["/UserByRestId", "/UserByScreenName"],
            timeout=15.0,
        )
        u = (pw.get("data") or {}).get("data", {}).get("user", {}).get("result", {})
        return (
            (u.get("core") or {}).get("screen_name")
            or (u.get("legacy") or {}).get("screen_name")
        )
    except Exception:  # noqa: BLE001
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
