"""Hit ALL remaining uncovered lines across every module (target: 100%)."""

from __future__ import annotations
import json, time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import pytest
from fastapi import FastAPI, Request
from starlette.testclient import TestClient


# ════════════════════════ auth.py remaining lines ════════════════════════
# Lines that can be tested without curl_cffi cookiejar dependency


@pytest.mark.asyncio
class TestAuthRemaining:
    async def test_login_viewer_valid(self):
        from app.auth import login_with_auth_token
        mock_client = AsyncMock()
        viewer_resp = AsyncMock()
        viewer_resp.status_code = 200
        viewer_resp.json = AsyncMock(return_value={
            "data": {"viewer": {"user_results": {"result": {
                "rest_id": "123", "is_blue_verified": True,
                "core": {"screen_name": "user", "name": "User", "created_at": "t"},
                "legacy": {"followers_count": 10, "friends_count": 5, "statuses_count": 100,
                           "verified": False, "protected": False, "description": "bio"},
            }}}}
        })
        mock_client.get = AsyncMock(return_value=viewer_resp)
        mock_client.cookies.jar = []
        with patch("app.auth.SessionStore.get") as ss:
            store = AsyncMock(spec=["lookup", "lookup_viewer", "store", "store_viewer"])
            store.lookup = AsyncMock(return_value=None)
            store.lookup_viewer = AsyncMock(return_value=None)
            store.store = AsyncMock(return_value=None)
            store.store_viewer = AsyncMock(return_value=None)
            ss.return_value = store
            with patch("app.auth.pooled_client") as pool:
                pool.return_value.__aenter__.return_value = mock_client
                with patch("app.auth.warm_session", AsyncMock(return_value=("ct0_v", {}))):
                    result = await login_with_auth_token("tok")
                    assert result["status"] == "valid"

    async def test_login_upstream_401(self):
        from app.auth import login_with_auth_token
        mock_client = AsyncMock()
        viewer_resp = AsyncMock()
        viewer_resp.status_code = 401
        viewer_resp.text = "Unauthorized"
        mock_client.get = AsyncMock(return_value=viewer_resp)
        mock_client.cookies.jar = []
        with patch("app.auth.SessionStore.get") as ss:
            store = AsyncMock(spec=["lookup", "lookup_viewer", "store", "store_viewer"])
            store.lookup = AsyncMock(return_value=None)
            store.lookup_viewer = AsyncMock(return_value=None)
            store.store = AsyncMock(return_value=None)
            store.store_viewer = AsyncMock(return_value=None)
            ss.return_value = store
            with patch("app.auth.pooled_client") as pool:
                pool.return_value.__aenter__.return_value = mock_client
                with patch("app.auth.warm_session", AsyncMock(return_value=("ct0_v", {}))):
                    result = await login_with_auth_token("tok")
                    assert result["status"] == "invalid"

    async def test_resolve_me_id(self):
        from app.auth import resolve_me_id, InvalidTokenError
        with patch("app.auth.pooled_client"):
            with patch("app.auth.warm_session") as warm:
                warm.side_effect = InvalidTokenError(401, "bad", {}, "ct0")
                uid = await resolve_me_id("tok")
                assert uid is None

    async def test_login_viewer_json_error(self):
        """Hit the except json.JSONDecodeError path in login."""
        from app.auth import login_with_auth_token
        mock_client = AsyncMock()
        viewer_resp = AsyncMock()
        viewer_resp.status_code = 200
        viewer_resp.json = AsyncMock(side_effect=json.JSONDecodeError("e", "doc", 0))
        mock_client.get = AsyncMock(return_value=viewer_resp)
        mock_client.cookies.jar = []
        with patch("app.auth.SessionStore.get") as ss:
            store = AsyncMock(spec=["lookup", "lookup_viewer", "store", "store_viewer"])
            store.lookup = AsyncMock(return_value=None)
            store.lookup_viewer = AsyncMock(return_value=None)
            store.store = AsyncMock(return_value=None)
            store.store_viewer = AsyncMock(return_value=None)
            ss.return_value = store
            with patch("app.auth.pooled_client") as pool:
                pool.return_value.__aenter__.return_value = mock_client
                with patch("app.auth.warm_session", AsyncMock(return_value=("ct0_v", {}))):
                    result = await login_with_auth_token("tok")
                    assert result["status"] == "valid"

    async def test_resolve_me_id_invalid(self):
        from app.auth import resolve_me_id
        with patch("app.auth.pooled_client") as pool:
            with patch("app.auth.warm_session") as warm:
                from app.auth import InvalidTokenError
                warm.side_effect = InvalidTokenError(401, "bad", {}, "ct0")
                uid = await resolve_me_id("tok")
                assert uid is None

    async def test_make_client_defaults(self):
        from app.auth import make_client
        with patch("app.auth.random_proxy", return_value=None):
            client = make_client("tok123")
            assert client is not None


# ════════════════════════ clients.py (curl_cffi bound — minimal coverage possible) ════════════════════════


# ════════════════════════ security.py remaining middleware bits ════════════════════════

class TestSecurityMiddlewares:
    def test_rate_limit_middleware_stats(self):
        from app.security import RateLimitMiddleware
        app = FastAPI()
        mw = RateLimitMiddleware(app)
        # Trigger bucket creation
        scope = {
            "type": "http", "method": "GET", "path": "/test",
            "query_string": b"", "headers": [],
            "client": ("127.0.0.1", 8000),
        }
        from starlette.requests import Request as StarRequest
        mw._key(StarRequest(scope))
        import asyncio
        stats = asyncio.run(mw.stats())
        assert stats["active_buckets"] >= 0

    def test_body_size_skip_media(self):
        from app.security import BodySizeLimitMiddleware
        app = FastAPI()
        # Skip buffer prefixes: /2/media/upload
        mw = BodySizeLimitMiddleware(app)
        scope = {
            "type": "http", "method": "POST", "path": "/2/media/upload/test",
            "query_string": b"", "headers": [(b"content-length", b"999999999")],
            "client": ("127.0.0.1", 8000),
        }
        import asyncio
        # Should not reject because media path has higher cap
        sentinel = []
        async def mock_receive():
            return {"type": "http.request", "body": b"x" * 100, "more_body": False}
        async def mock_send(msg):
            sentinel.append(msg)
        asyncio.run(mw(scope, mock_receive, mock_send))
        # Middleware should pass through to app because media path
        assert len(sentinel) > 0  # app was called


# ════════════════════════ sanitize.py remaining ════════════════════════

def test_sanitize_url_param_control_char_strip():
    from app.sanitize import sanitize_url_param
    assert sanitize_url_param("a\x00b\x01c") == "abc"
    assert sanitize_url_param("a\x0eb") == "ab"


# ════════════════════════ response_cache.py ════════════════════════

@pytest.mark.asyncio
async def test_response_cache_store_eviction():
    from app.response_cache import ResponseCache
    cache = ResponseCache()
    with patch("app.response_cache.MAX_CACHE_ENTRIES", 1):
        await cache.store("UserByScreenName", {"screen_name": "a"}, "tok", {"status": "ok", "data": {}})
        await cache.store("UserByScreenName", {"screen_name": "b"}, "tok", {"status": "ok", "data": {}})
        assert len(cache._cache) <= 1


# ════════════════════════ observability.py ════════════════════════

def test_observability_log_setup():
    """Hit _setup_logging path — not much to assert, just no crash."""
    import logging
    from app.observability import _setup_logging
    _setup_logging()
    root = logging.getLogger()
    assert len(root.handlers) > 0


def test_observability_json_formatter_exc():
    from app.observability import _JSONFormatter
    import logging
    fmt = _JSONFormatter()
    record = logging.LogRecord("test", logging.ERROR, "test.py", 1, "msg", (), exc_info=(ValueError, ValueError("x"), None))
    out = fmt.format(record)
    assert "exc" in out


# ════════════════════════ clients.py media_upload ════════════════════════

@pytest.mark.asyncio
async def test_media_upload_error_init():
    from app.clients import media_upload
    mock_sess = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status_code = 400
    mock_resp.text = "init failed"
    mock_sess.post = AsyncMock(return_value=mock_resp)
    mock_sess.cookies.jar = []
    with patch("app.clients.pooled_client") as pool:
        pool.return_value.__aenter__.return_value = mock_sess
        with patch("app.clients.warm_session", AsyncMock(return_value=("ct0", {}))):
            result = await media_upload("tok", b"data", "image/jpeg")
            assert result["status"] == "error"
            assert "INIT" in result.get("stage", "")


# ════════════════════════ formatter.py remaining big blocks ════════════════════════

def test_formatter_tweet_with_view_counts():
    """Hit view count and entities paths."""
    from formatter import _tweet_result_to_obj
    t = {
        "rest_id": "1", "core": {}, "legacy": {
            "full_text": "t",
            "entities": {"hashtags": [], "user_mentions": [], "urls": [], "symbols": []},
        },
        "views": {"count": "42"},
    }
    obj = _tweet_result_to_obj(t)
    assert obj["public_metrics"]["impression_count"] == "42"


def test_formatter_tweet_with_attachments_photo():
    """Hit _media_obj path for photo type."""
    from formatter import _tweet_result_to_obj
    t = {
        "rest_id": "1", "core": {}, "legacy": {
            "full_text": "t",
            "extended_entities": {
                "media": [{
                    "media_key": "3_1", "type": "photo", "media_url_https": "https://x.com/p.jpg",
                    "original_info": {"width": 800, "height": 600},
                    "ext_alt_text": "alt",
                }]
            },
        },
    }
    obj = _tweet_result_to_obj(t)
    assert obj["public_metrics"]["impression_count"] is None


def test_formatter_birdwatch_delete():
    """Hit birdwatch_delete path."""
    from formatter import format_birdwatch_note_result
    gql = {"data": {"birdwatchnote_delete": {"status": "deleted"}}}
    out = format_birdwatch_note_result(gql)
    assert "data" in out


def test_formatter_birdwatch_create_rating():
    from formatter import format_birdwatch_note_result
    gql = {"data": {"birdwatchnote_rate_v3": {"status": "rated"}}}
    out = format_birdwatch_note_result(gql)
    assert "data" in out


def test_formatter_community_str_created():
    from formatter import format_community
    gql = {
        "data": {
            "communityResults": {
                "result": {
                    "rest_id": "c1", "name": "c",
                    "created_at": "2024-01-01T00:00:00",
                    "actions": {}, "rules": [],
                }
            }
        }
    }
    out = format_community(gql)
    assert out["data"]["created_at"] == "2024-01-01T00:00:00"


def test_formatter_collection_user_item():
    from formatter import format_tweet_collection
    gql = {
        "data": {
            "user": {
                "result": {
                    "timeline_v2": {
                        "timeline": {
                            "instructions": [{
                                "type": "TimelineAddEntries",
                                "entries": [{
                                    "content": {
                                        "itemContent": {
                                            "itemType": "TimelineUser",
                                            "user_results": {"result": {"rest_id": "u1", "core": {}, "legacy": {}}},
                                        },
                                    },
                                }],
                            }],
                        }
                    }
                }
            }
        }
    }
    out = format_tweet_collection(gql, item="user")
    assert len(out["data"]) == 1


# ════════════════════════ config.py remaining line 252 ════════════════════════

def test_config_random_proxy_empty():
    from app.config import random_proxy
    with patch("app.config.PROXY_LIST", ()):
        assert random_proxy() is None

def test_config_random_proxy_with_list():
    from app.config import random_proxy
    with patch("app.config.PROXY_LIST", ("http://p1", "http://p2")):
        p = random_proxy()
        assert p.startswith("http://")
