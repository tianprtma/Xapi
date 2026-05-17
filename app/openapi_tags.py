"""OpenAPI tag definitions + auto-tagger by URL pattern.

Mengelompokkan endpoint di /docs mirip docs.x.com — semua route otomatis
ke-tag berdasarkan URL prefix tanpa perlu `tags=[...]` di setiap decorator.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "Users", "description": "Profile, search, lookups, followers/following, blocks/mutes."},
    {"name": "Tweets", "description": "Tweet read/write, likes, retweets, search, replies, moderation."},
    {"name": "Timelines", "description": "Home + reverse-chronological timelines."},
    {"name": "Lists", "description": "List CRUD, members, subscriptions, pinning."},
    {"name": "Bookmarks", "description": "Bookmarks + bookmark folders."},
    {"name": "Communities", "description": "X Communities (read-only via cookie)."},
    {"name": "Birdwatch", "description": "Community Notes (write/read/rate, contributor profile, BatSignal)."},
    {"name": "Direct Messages", "description": "DM events + conversations via REST 1.1 internal."},
    {"name": "Spaces", "description": "Audio Spaces (mostly stub — butuh trigger /i/spaces page)."},
    {"name": "Trends", "description": "Trending topics by location/woeid + personalized trends."},
    {"name": "Media", "description": "Media upload (chunked init/append/finalize) + metadata."},
    {"name": "Infra", "description": "Login, cache, TID stats, source inspect."},
]


def auto_tag(path: str) -> str:
    """Decide tag for an endpoint path by URL pattern."""
    p = path

    # Infra (root, login, search, stats)
    if p in ("/", "/login", "/search", "/cache/stats", "/tid/stats"):
        return "Infra"

    # Direct Messages + Chat
    if (p.startswith("/2/dm_") or p.startswith("/2/dm/") or p.startswith("/2/chat") or
            "/dm_conversations" in p or "/dm_events" in p or "/dm/" in p):
        return "Direct Messages"

    # Birdwatch / Notes
    if p.startswith("/2/notes") or p == "/2/evaluate_note":
        return "Birdwatch"

    # Communities
    if p.startswith("/2/communities"):
        return "Communities"

    # Spaces
    if p.startswith("/2/spaces"):
        return "Spaces"

    # Lists (cover both /2/lists/* and user-scoped list ops)
    if p.startswith("/2/lists"):
        return "Lists"
    if any(seg in p for seg in (
        "/owned_lists", "/pinned_lists", "/list_memberships", "/followed_lists",
    )):
        return "Lists"

    # Bookmarks (folders + bookmarks)
    if "/bookmarks" in p:
        return "Bookmarks"

    # Trends
    if p.startswith("/2/trends") or "/personalized_trends" in p:
        return "Trends"

    # Media
    if p.startswith("/2/media"):
        return "Media"

    # Tweets (search/replies/moderation/retweets/likes)
    if p.startswith("/2/tweets"):
        return "Tweets"
    if "/likes/" in p or p.endswith("/likes") or p.endswith("/retweets") or "/retweets/" in p:
        return "Tweets"

    # Timelines
    if p.startswith("/2/home_timeline") or "/timelines/reverse_chronological" in p:
        return "Timelines"

    # Users (catch-all under /2/users)
    if p.startswith("/2/users"):
        return "Users"

    return "Other"


def install_auto_tagger(app: FastAPI) -> None:
    """Override `app.openapi` so any untagged route gets auto-tagged."""

    def _custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=OPENAPI_TAGS,
        )
        for path, methods in schema.get("paths", {}).items():
            for _, op in methods.items():
                if not isinstance(op, dict):
                    continue
                if op.get("tags"):
                    continue
                op["tags"] = [auto_tag(path)]
        app.openapi_schema = schema
        return schema

    app.openapi = _custom_openapi
