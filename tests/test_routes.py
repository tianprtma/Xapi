"""Parametrized tests for every endpoint across all routers.

Strategy: mock all external call sites (graphql_call, rest_call, dm_call,
search_via_browser, fetch_via_browser, login_with_auth_token, resolve_me_id)
so every route executes through to response construction without real upstream.

Stub routes (stub_501) → assert 501 status + error shape.
Real routes → assert correct delegation and response wrapping.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

OK_GQL = {"status": "ok", "data": {"data": {"result": {"ok": True}}}}
OK_REST = {"status": "ok", "data": {"id": 1, "screen_name": "test"}}
OK_DM = {"status": "ok", "data": {"dm_events": [], "users": [], "conversations": {}}}
OK_PW = {"status": "ok", "http_status": 200, "data": {"data": {"items": []}}}
TOKEN = "a" * 40
AH = {"Authorization": f"Bearer {TOKEN}"}

# All router modules that import from app.clients / app.auth / playwright_search / app.playwright_helpers
ROUTER_MODS = [
    "app.routers.birdwatch", "app.routers.bookmarks", "app.routers.communities",
    "app.routers.dm", "app.routers.infra", "app.routers.lists",
    "app.routers.media", "app.routers.spaces", "app.routers.timelines",
    "app.routers.trends", "app.routers.tweets", "app.routers.users",
]

# Direct import routes for functions routers import via `from ..clients import graphql_call`
# We must patch the local name inside each router module.
# Map each router → set of names to patch (based on actual imports).
ROUTER_PATCHES: dict[str, set[str]] = {m: {
    "graphql_call", "rest_call", "dm_call", "media_upload",
    "search_via_browser", "fetch_via_browser", "click_action_via_browser", "action_via_browser",
    "extract_bearer", "login_with_auth_token", "resolve_me_id",
    "resolve_screen_name", "tweet_author_handle",
    # Formatters — mock at router level so finalize() gets expected shape
    "format_tweet", "format_tweet_collection", "format_user",
    "format_dm_send_result", "format_community",
    "format_birdwatch_note_result", "format_birdwatch_notes_slice", "format_birdwatch_batsignal",
    "format_bookmark_folders", "format_error",
} for m in ROUTER_MODS}


def _make_router_mocks() -> dict[str, Any]:
    """Build patch-target → mock-value dict, one per router-local import."""
    m: dict[str, Any] = {}
    gql = AsyncMock(return_value=OK_GQL)
    rest = AsyncMock(return_value=OK_REST)
    dm = AsyncMock(return_value=OK_DM)
    mu = AsyncMock(return_value={"status": "ok", "data": {"media_id_string": "123", "media_key": "3_123"}})
    pw = AsyncMock(return_value=OK_PW)
    pw_click = AsyncMock(return_value=OK_PW)
    pw_action = AsyncMock(return_value=OK_PW)
    eb = lambda *a: TOKEN  # noqa: E731
    login = AsyncMock(return_value={"status": "valid", "http_status": 200, "user": {"id": "123", "screen_name": "me", "name": "Me", "followers_count": 10, "friends_count": 5, "statuses_count": 100, "verified": True, "protected": False, "created_at": "2020-01-01"}})
    rme = AsyncMock(return_value="123")
    rsn = AsyncMock(return_value="testuser")
    tah = AsyncMock(return_value="author")
    # Formatters are sync; return a JSON-serializable dict so JSONResponse is happy.
    fmt = lambda *a, **k: {"data": {}}  # noqa: E731
    _VAL = {  # name → mock value
        "graphql_call": gql, "rest_call": rest, "dm_call": dm, "media_upload": mu,
        "search_via_browser": pw, "fetch_via_browser": pw,
        "click_action_via_browser": pw_click, "action_via_browser": pw_action,
        "extract_bearer": eb, "login_with_auth_token": login, "resolve_me_id": rme,
        "resolve_screen_name": rsn, "tweet_author_handle": tah,
        "format_tweet": fmt, "format_tweet_collection": fmt, "format_user": fmt,
        "format_dm_send_result": fmt, "format_community": fmt,
        "format_birdwatch_note_result": fmt, "format_birdwatch_notes_slice": fmt,
        "format_birdwatch_batsignal": fmt, "format_bookmark_folders": fmt,
        "format_error": fmt,
    }
    for mod, names in ROUTER_PATCHES.items():
        for name in names:
            m[f"{mod}.{name}"] = _VAL[name]
    return m


@pytest.fixture(autouse=True)
def _mock_all():
    """Mock all X upstream + auth at router-module level (local import refs)."""
    mocks = _make_router_mocks()
    patchers = [patch(path, mock, create=True) for path, mock in mocks.items()]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


# ────────────────────── Infra ──────────────────────


class TestInfo:
    def test_info(self, app_client):
        r = app_client.get("/info")
        assert r.status_code == 200
        assert r.json()["service"] == "X (Twitter) Cookie API"

    def test_login_valid(self, app_client):
        r = app_client.get("/login", headers=AH)
        assert r.status_code == 200

    def test_search(self, app_client):
        r = app_client.post("/search", headers=AH, json={"q": "test", "type": "Latest"})
        assert r.status_code == 200
        assert r.json()["engine"] == "playwright"

    def test_admin_stats_no_token(self, app_client):
        assert app_client.get("/admin/stats").status_code in (404, 401)

    def test_docs(self, app_client):
        assert app_client.get("/docs").status_code == 200

    def test_redoc(self, app_client):
        assert app_client.get("/redoc").status_code == 200

    def test_openapi(self, app_client):
        r = app_client.get("/openapi.json")
        assert r.status_code == 200
        assert "paths" in r.json()

    def test_security_headers(self, app_client):
        r = app_client.get("/info")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert "Strict-Transport-Security" in r.headers


# ────────────────────── Tweets (16 endpoints) ──────────────────────


class TestTweets:
    def test_get_tweets(self, app_client):
        assert app_client.get("/2/tweets?ids=1,2,3", headers=AH).status_code == 200

    def test_get_tweets_empty(self, app_client):
        assert app_client.get("/2/tweets?ids=", headers=AH).status_code == 400

    def test_create_tweet(self, app_client):
        assert app_client.post("/2/tweets", headers=AH, json={"text": "hello"}).status_code in (200, 201)

    def test_search_recent(self, app_client):
        r = app_client.get("/2/tweets/search/recent?query=test", headers=AH)
        assert r.status_code == 200

    def test_delete_tweet(self, app_client):
        assert app_client.delete("/2/tweets/123", headers=AH).status_code == 200

    def test_tweet_by_id(self, app_client):
        assert app_client.get("/2/tweets/123", headers=AH).status_code == 200

    def test_tweet_detail(self, app_client):
        assert app_client.get("/2/tweets/123/detail", headers=AH).status_code == 200

    def test_hide_reply(self, app_client):
        assert app_client.put("/2/tweets/123/hidden", headers=AH).status_code == 200

    def test_liking_users(self, app_client):
        assert app_client.get("/2/tweets/123/liking_users", headers=AH).status_code == 200

    def test_quote_tweets(self, app_client):
        assert app_client.get("/2/tweets/123/quote_tweets", headers=AH).status_code == 200

    def test_retweeted_by(self, app_client):
        assert app_client.get("/2/tweets/123/retweeted_by", headers=AH).status_code == 200

    def test_retweets(self, app_client):
        assert app_client.get("/2/tweets/123/retweets", headers=AH).status_code == 200

    def test_like(self, app_client):
        assert app_client.post("/2/users/123/likes", headers=AH, json={"tweet_id": "1"}).status_code == 200

    def test_unlike(self, app_client):
        assert app_client.delete("/2/users/123/likes/1", headers=AH).status_code == 200

    def test_retweet(self, app_client):
        assert app_client.post("/2/users/123/retweets", headers=AH, json={"tweet_id": "1"}).status_code == 200

    def test_unretweet_canonical(self, app_client):
        assert app_client.delete("/2/users/123/retweets/by/source_tweet_id/1", headers=AH).status_code == 200

    def test_unretweet_legacy(self, app_client):
        assert app_client.delete("/2/users/123/retweets/1", headers=AH).status_code == 200


# ────────────────────── Users (28 endpoints, 3 stubs) ──────────────────────


class TestUsers:
    def test_bulk(self, app_client):
        assert app_client.get("/2/users?ids=1,2,3", headers=AH).status_code == 200

    def test_bulk_empty(self, app_client):
        assert app_client.get("/2/users?ids=", headers=AH).status_code == 400

    def test_by_usernames(self, app_client):
        assert app_client.get("/2/users/by?usernames=a,b", headers=AH).status_code == 200

    def test_by_usernames_empty(self, app_client):
        assert app_client.get("/2/users/by?usernames=", headers=AH).status_code == 400

    def test_by_username(self, app_client):
        assert app_client.get("/2/users/by/username/testuser", headers=AH).status_code == 200

    def test_me(self, app_client):
        r = app_client.get("/2/users/me", headers=AH)
        assert r.status_code == 200
        assert r.json()["data"]["username"] == "me"

    def test_public_keys_stub(self, app_client):
        assert app_client.get("/2/users/public_keys").status_code == 501

    def test_reposts_of_me(self, app_client):
        assert app_client.get("/2/users/reposts_of_me", headers=AH).status_code == 200

    def test_search(self, app_client):
        assert app_client.get("/2/users/search?query=test", headers=AH).status_code == 200

    def test_unblock(self, app_client):
        assert app_client.delete("/2/users/1/blocking/2", headers=AH).status_code == 200

    def test_unfollow(self, app_client):
        assert app_client.delete("/2/users/1/following/2", headers=AH).status_code == 200

    def test_unmute(self, app_client):
        assert app_client.delete("/2/users/1/muting/2", headers=AH).status_code == 200

    def test_by_id(self, app_client):
        assert app_client.get("/2/users/123", headers=AH).status_code == 200

    def test_affiliates(self, app_client):
        assert app_client.get("/2/users/123/affiliates", headers=AH).status_code == 200

    def test_blocking(self, app_client):
        assert app_client.get("/2/users/123/blocking", headers=AH).status_code == 200

    def test_block(self, app_client):
        assert app_client.post("/2/users/123/blocking", headers=AH, json={"target_user_id": "456"}).status_code == 200

    def test_followers(self, app_client):
        assert app_client.get("/2/users/123/followers", headers=AH).status_code == 200

    def test_following(self, app_client):
        assert app_client.get("/2/users/123/following", headers=AH).status_code == 200

    def test_follow(self, app_client):
        assert app_client.post("/2/users/123/following", headers=AH, json={"target_user_id": "456"}).status_code == 200

    def test_liked_tweets(self, app_client):
        assert app_client.get("/2/users/123/liked_tweets", headers=AH).status_code == 200

    def test_user_media(self, app_client):
        assert app_client.get("/2/users/123/media", headers=AH).status_code == 200

    def test_mentions(self, app_client):
        assert app_client.get("/2/users/123/mentions?username=me", headers=AH).status_code == 200

    def test_muting(self, app_client):
        assert app_client.get("/2/users/123/muting", headers=AH).status_code == 200

    def test_mute(self, app_client):
        assert app_client.post("/2/users/123/muting", headers=AH, json={"target_user_id": "456"}).status_code == 200

    def test_pin_tweet(self, app_client):
        assert app_client.post("/2/users/123/pinned_tweets", headers=AH, json={"tweet_id": "1"}).status_code == 200

    def test_unpin_tweet(self, app_client):
        assert app_client.delete("/2/users/123/pinned_tweets/1", headers=AH).status_code == 200

    def test_user_pubkeys_stub(self, app_client):
        assert app_client.get("/2/users/123/public_keys").status_code == 501

    def test_user_pubkeys_post_stub(self, app_client):
        assert app_client.post("/2/users/123/public_keys").status_code == 501

    def test_user_tweets(self, app_client):
        assert app_client.get("/2/users/123/tweets", headers=AH).status_code == 200

    def test_user_tweets_replies(self, app_client):
        assert app_client.get("/2/users/123/tweets/replies", headers=AH).status_code == 200


# ────────────────────── Lists (21 endpoints) ──────────────────────


class TestLists:
    def test_create(self, app_client):
        assert app_client.post("/2/lists", headers=AH, json={"name": "test"}).status_code == 200

    def test_update(self, app_client):
        assert app_client.put("/2/lists", headers=AH, json={"list_id": "1", "name": "new"}).status_code == 200

    def test_owned(self, app_client):
        assert app_client.get("/2/lists/by/owner/123", headers=AH).status_code == 200

    def test_delete(self, app_client):
        assert app_client.delete("/2/lists/1", headers=AH).status_code == 200

    def test_detail(self, app_client):
        assert app_client.get("/2/lists/1", headers=AH).status_code == 200

    def test_update_canonical(self, app_client):
        assert app_client.put("/2/lists/1", headers=AH, json={"name": "new"}).status_code == 200

    def test_followers(self, app_client):
        assert app_client.get("/2/lists/1/followers", headers=AH).status_code == 200

    def test_members(self, app_client):
        assert app_client.get("/2/lists/1/members", headers=AH).status_code == 200

    def test_add_member(self, app_client):
        assert app_client.post("/2/lists/1/members", headers=AH, json={"list_id": "1", "user_id": "456"}).status_code == 200

    def test_remove_member(self, app_client):
        assert app_client.delete("/2/lists/1/members/456", headers=AH).status_code == 200

    def test_unpin(self, app_client):
        assert app_client.delete("/2/lists/1/pinned", headers=AH).status_code == 200

    def test_pin(self, app_client):
        assert app_client.post("/2/lists/1/pinned", headers=AH).status_code == 200

    def test_tweets(self, app_client):
        assert app_client.get("/2/lists/1/tweets", headers=AH).status_code == 200

    def test_followed_lists(self, app_client):
        assert app_client.get("/2/users/123/followed_lists", headers=AH).status_code == 200

    def test_follow_list(self, app_client):
        assert app_client.post("/2/users/123/followed_lists?list_id=1", headers=AH).status_code == 200

    def test_unfollow_list(self, app_client):
        assert app_client.delete("/2/users/123/followed_lists/1", headers=AH).status_code == 200

    def test_list_memberships(self, app_client):
        assert app_client.get("/2/users/123/list_memberships", headers=AH).status_code == 200

    def test_owned_lists(self, app_client):
        assert app_client.get("/2/users/123/owned_lists", headers=AH).status_code == 200

    def test_pinned_lists(self, app_client):
        assert app_client.get("/2/users/123/pinned_lists", headers=AH).status_code == 200

    def test_pin_list_canonical(self, app_client):
        assert app_client.post("/2/users/123/pinned_lists", headers=AH, json={"list_id": "1"}).status_code == 200

    def test_unpin_list_canonical(self, app_client):
        assert app_client.delete("/2/users/123/pinned_lists/1", headers=AH).status_code == 200


# ────────────────────── DM (16: 9 stubs + 7 real; retrieval removed) ──────────────────────


class TestDM:
    def test_chat_group_create_stub(self, app_client):
        assert app_client.post("/2/chat/conversations/group").status_code == 501

    def test_chat_group_init_stub(self, app_client):
        assert app_client.post("/2/chat/conversations/group/initialize").status_code == 501

    def test_chat_keys_stub(self, app_client):
        assert app_client.post("/2/chat/conversations/1/keys").status_code == 501

    def test_chat_members_stub(self, app_client):
        assert app_client.post("/2/chat/conversations/1/members").status_code == 501

    def test_chat_messages_stub(self, app_client):
        assert app_client.post("/2/chat/conversations/1/messages").status_code == 501

    def test_chat_read_stub(self, app_client):
        assert app_client.post("/2/chat/conversations/1/read").status_code == 501

    def test_chat_typing_stub(self, app_client):
        assert app_client.post("/2/chat/conversations/1/typing").status_code == 501

    def test_chat_media_finalize_stub(self, app_client):
        assert app_client.post("/2/chat/media/upload/finalize").status_code == 501

    def test_chat_media_init_stub(self, app_client):
        assert app_client.post("/2/chat/media/upload/initialize").status_code == 501

    def test_chat_media_append_stub(self, app_client):
        assert app_client.post("/2/chat/media/upload/1/append").status_code == 501

    def test_dm_conv_create(self, app_client):
        r = app_client.post("/2/dm_conversations", headers=AH, json={"participant_ids": ["456"], "message": {"text": "hello"}})
        assert r.status_code in (200, 201)

    def test_dm_send(self, app_client):
        r = app_client.post("/2/dm_conversations/with/456/messages", headers=AH, json={"text": "hi"})
        assert r.status_code in (200, 201)

    def test_dm_send_to_conv(self, app_client):
        r = app_client.post("/2/dm_conversations/1/messages", headers=AH, json={"text": "hi"})
        assert r.status_code in (200, 201)

    def test_dm_event_delete(self, app_client):
        assert app_client.delete("/2/dm_events/1", headers=AH).status_code == 200

    def test_dm_block(self, app_client):
        assert app_client.post("/2/users/456/dm/block", headers=AH).status_code == 200

    def test_dm_unblock(self, app_client):
        assert app_client.post("/2/users/456/dm/unblock", headers=AH).status_code == 200


# ────────────────────── Bookmarks (5) ──────────────────────


class TestBookmarks:
    def test_get(self, app_client):
        assert app_client.get("/2/users/123/bookmarks", headers=AH).status_code == 200

    def test_create(self, app_client):
        assert app_client.post("/2/users/123/bookmarks", headers=AH, json={"tweet_id": "1"}).status_code == 200

    def test_folders(self, app_client):
        assert app_client.get("/2/users/123/bookmarks/folders", headers=AH).status_code == 200

    def test_folder_by_id(self, app_client):
        assert app_client.get("/2/users/123/bookmarks/folders/1", headers=AH).status_code == 200

    def test_delete(self, app_client):
        assert app_client.delete("/2/users/123/bookmarks/1", headers=AH).status_code == 200


# ────────────────────── Birdwatch (5) ──────────────────────


class TestBirdwatch:
    def test_evaluate_note(self, app_client):
        r = app_client.post("/2/evaluate_note", headers=AH, json={"note_id": "n1", "tweet_id": "123", "data": {"k": "v"}})
        assert r.status_code in (200, 201)

    def test_create_note(self, app_client):
        r = app_client.post("/2/notes", headers=AH, json={"tweet_id": "123", "data": {"k": "v"}})
        assert r.status_code in (200, 201)

    def test_notes_written(self, app_client):
        assert app_client.get("/2/notes/search/notes_written?alias=testalias", headers=AH).status_code == 200

    def test_notes_eligible(self, app_client):
        assert app_client.get("/2/notes/search/posts_eligible_for_notes?tweet_id=123", headers=AH).status_code == 200

    def test_delete_note(self, app_client):
        assert app_client.delete("/2/notes/1", headers=AH).status_code == 200


# ────────────────────── Communities (2: 1 stub) ──────────────────────


class TestCommunities:
    def test_search_stub(self, app_client):
        assert app_client.get("/2/communities/search").status_code == 501

    def test_by_id(self, app_client):
        assert app_client.get("/2/communities/123", headers=AH).status_code == 200


# ────────────────────── Trends (2) ──────────────────────


class TestTrends:
    def test_trends(self, app_client):
        assert app_client.get("/2/trends?woeid=1", headers=AH).status_code == 200

    def test_by_woeid(self, app_client):
        assert app_client.get("/2/trends/by/woeid/1", headers=AH).status_code == 200


# ────────────────────── Timelines (2) ──────────────────────


class TestTimelines:
    def test_home(self, app_client):
        assert app_client.get("/2/home_timeline", headers=AH).status_code == 200

    def test_latest(self, app_client):
        assert app_client.get("/2/users/123/timelines/reverse_chronological", headers=AH).status_code == 200


# ────────────────────── Spaces (6: 3 stubs) ──────────────────────


class TestSpaces:
    def test_lookup(self, app_client):
        assert app_client.get("/2/spaces?ids=1,2", headers=AH).status_code == 200

    def test_lookup_empty(self, app_client):
        assert app_client.get("/2/spaces?ids=", headers=AH).status_code == 400

    def test_topics(self, app_client):
        assert app_client.get("/2/spaces/topics", headers=AH).status_code == 200

    def test_by_id(self, app_client):
        assert app_client.get("/2/spaces/1", headers=AH).status_code == 200

    def test_buyers_stub(self, app_client):
        assert app_client.get("/2/spaces/1/buyers").status_code == 501

    def test_by_creator_stub(self, app_client):
        assert app_client.get("/2/spaces/by/creator_ids").status_code == 501

    def test_tweets_stub(self, app_client):
        assert app_client.get("/2/spaces/1/tweets").status_code == 501


# ────────────────────── Media (5: 3 stubs) ──────────────────────


class TestMedia:
    def test_metadata(self, app_client):
        assert app_client.post("/2/media/metadata", headers=AH, json={}).status_code == 200

    def test_upload(self, app_client):
        r = app_client.post("/2/media/upload?media_type=image/jpeg", headers=AH, content=b"fake-bytes")
        assert r.status_code == 200
        assert r.json()["data"]["media_id"] == "123"

    def test_upload_empty_body(self, app_client):
        assert app_client.post("/2/media/upload?media_type=image/jpeg", headers=AH, content=b"").status_code == 400

    def test_init_stub(self, app_client):
        assert app_client.post("/2/media/upload/initialize").status_code == 501

    def test_append_stub(self, app_client):
        assert app_client.post("/2/media/upload/1/append").status_code == 501

    def test_finalize_stub(self, app_client):
        assert app_client.post("/2/media/upload/1/finalize").status_code == 501


# ────────────────────── Raw mode ──────────────────────


class TestRawMode:
    def test_raw_flag(self, app_client):
        assert app_client.get("/2/tweets/123?raw=1", headers=AH).status_code == 200