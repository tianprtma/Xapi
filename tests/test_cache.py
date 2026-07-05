"""Tests for session_cache.py and app/response_cache.py."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.response_cache import ResponseCache, _key, CACHEABLE_OPS, PLAYWRIGHT_CACHEABLE_OPS
from app.config import RESPONSE_CACHE_TTL


# ════════════════════════ SessionStore tests ════════════════════════


class TestSession:
    def test_create(self):
        from session_cache import Session, TTL_SECONDS
        s = Session(auth_token="tok1", ct0="ct0_1", cookies={"a": "b"})
        assert s.is_alive(TTL_SECONDS) is True
        assert s.user_id is None

    def test_expired(self):
        from session_cache import Session
        s = Session(auth_token="tok1", ct0="ct0_1", cookies={})
        s.last_used = 0  # force expired
        assert s.is_alive(ttl=1) is False

    def test_viewer_alive(self):
        from session_cache import Session
        s = Session(auth_token="tok1", ct0="ct0_1", cookies={})
        assert s.viewer_alive() is False  # no viewer set
        s.viewer = {"status": "valid"}
        s.last_used = time.time()
        assert s.viewer_alive() is True


@pytest.mark.asyncio
class TestSessionStore:
    async def test_store_and_lookup(self):
        from session_cache import SessionStore
        store = SessionStore()
        ss = await store.store("tok1", "ct0_1", {"twid": "u=123"})
        found = await store.lookup("tok1")
        assert found is not None
        assert found.ct0 == "ct0_1"

    async def test_lookup_expired(self):
        from session_cache import SessionStore
        store = SessionStore()
        await store.store("tok1", "ct0_1", {})
        # force expiry by using ttl=0
        found = await store.lookup("tok1", ttl=-1)
        assert found is None

    async def test_invalidate(self):
        from session_cache import SessionStore
        store = SessionStore()
        await store.store("tok1", "ct0_1", {})
        await store.invalidate("tok1")
        found = await store.lookup("tok1")
        assert found is None

    async def test_store_viewer(self):
        from session_cache import SessionStore
        store = SessionStore()
        await store.store("tok1", "ct0_1", {})
        await store.store_viewer("tok1", {"status": "valid", "user": {"id": "1"}})
        viewer = await store.lookup_viewer("tok1")
        assert viewer["status"] == "valid"

    async def test_lookup_viewer_expired(self):
        from session_cache import SessionStore
        store = SessionStore()
        await store.store("tok1", "ct0_1", {})
        await store.store_viewer("tok1", {"status": "valid"})
        found = await store.lookup_viewer("tok1", ttl=-1)
        assert found is None

    async def test_stats(self):
        from session_cache import SessionStore
        store = SessionStore()
        await store.store("tok1", "ct0_1", {"twid": "u=1"})
        await store.store("tok2", "ct0_2", {"twid": "u=2"})
        stats = await store.stats()
        assert stats["total"] == 2
        assert stats["max_sessions"] == 5000

    async def test_singleton(self):
        from session_cache import SessionStore
        s1 = SessionStore.get()
        s2 = SessionStore.get()
        assert s1 is s2


# ════════════════════════ ResponseCache tests ════════════════════════


@pytest.mark.asyncio
class TestResponseCache:
    async def test_is_cacheable(self):
        assert ResponseCache.is_cacheable("UserByScreenName") is (RESPONSE_CACHE_TTL > 0)
        assert ResponseCache.is_cacheable("_pw_search") is (RESPONSE_CACHE_TTL > 0)

    async def test_store_and_lookup(self):
        cache = ResponseCache()
        op = "UserByScreenName"
        vars = {"screen_name": "test"}
        tok = "tok1"
        payload = {"status": "ok", "data": {"result": {"id": "1"}}}
        await cache.store(op, vars, tok, payload)
        hit = await cache.lookup(op, vars, tok)
        assert hit is not None
        assert hit["data"]["result"]["id"] == "1"

    async def test_lookup_miss(self):
        cache = ResponseCache()
        hit = await cache.lookup("UserByScreenName", {"screen_name": "x"}, "tok")
        assert hit is None

    async def test_store_non_cacheable_op(self):
        cache = ResponseCache()
        await cache.store("UnknownOp", {}, "tok", {"status": "ok"})
        assert len(cache._cache) == 0

    async def test_store_error_payload_not_cached(self):
        cache = ResponseCache()
        await cache.store("UserByScreenName", {"screen_name": "x"}, "tok", {"status": "error"})
        assert len(cache._cache) == 0

    async def test_lookup_expired(self):
        cache = ResponseCache()
        op = "UserByScreenName"
        # Manually insert expired entry past TTL
        key = ("UserByScreenName", '{"screen_name": "x"}', "tok-key")
        import time
        cache._cache[key] = (time.time() - 9999, {"status": "ok", "data": {}})
        hit = await cache.lookup(op, {"screen_name": "x"}, "tok")
        assert hit is None

    async def test_singleton(self):
        c1 = ResponseCache.get()
        c2 = ResponseCache.get()
        assert c1 is c2

    async def test_stats(self):
        cache = ResponseCache()
        await cache.store("UserByScreenName", {"screen_name": "x"}, "tok", {"status": "ok", "data": {}})
        await cache.lookup("UserByScreenName", {"screen_name": "x"}, "tok")
        await cache.lookup("UserByScreenName", {"screen_name": "missing"}, "tok")
        stats = await cache.stats()
        assert stats["hits"] >= 1
        assert stats["misses"] >= 1


class TestCacheKey:
    def test_same_input_same_key(self):
        k1 = _key("UserByScreenName", {"screen_name": "x"}, "tok1")
        k2 = _key("UserByScreenName", {"screen_name": "x"}, "tok1")
        assert k1 == k2

    def test_diff_token_diff_key(self):
        k1 = _key("UserByScreenName", {"screen_name": "x"}, "tok1")
        k2 = _key("UserByScreenName", {"screen_name": "x"}, "tok2")
        assert k1 != k2
