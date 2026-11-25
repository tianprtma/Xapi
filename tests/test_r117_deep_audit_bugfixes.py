"""Regression tests for Round 20 deep algorithmic audit fixes in Xapi."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# 1. _enrich_conv_events_with_e2ee: None-timestamp sorting & exact-ID reservation
@pytest.mark.asyncio
async def test_enrich_conv_events_none_timestamp_sorted_last_and_exact_id_not_stolen():
    from app.routers.dm import _enrich_conv_events_with_e2ee

    # GraphQL events: newer unsynced encrypted event (gql_new, t=10:01:00) +
    # older synced encrypted event (opfs_1, t=10:00:00)
    formatted = {
        "data": [
            {
                "id": "gql_new",
                "event_type": "MessageCreate",
                "sender_id": "111",
                "created_at": "2026-11-24T10:01:00.000Z",
                "text": "[XChat E2EE Encrypted Message]",
                "_xchat_encrypted": True,
            },
            {
                "id": "opfs_1",
                "event_type": "MessageCreate",
                "sender_id": "111",
                "created_at": "2026-11-24T10:00:00.000Z",
                "text": "[XChat E2EE Encrypted Message]",
                "_xchat_encrypted": True,
            },
        ],
        "meta": {"result_count": 2},
    }
    decrypted = [
        {"id": "nodate_1", "event_type": "MessageCreate", "sender_id": "222", "text": "undated row", "created_at": None},
        {"id": "opfs_1", "event_type": "MessageCreate", "sender_id": "111", "text": "older exact text", "created_at": "2026-11-24T10:00:00.000Z"},
        {"id": "opfs_extra_new", "event_type": "MessageCreate", "sender_id": "222", "text": "newest extra", "created_at": "2026-11-24T10:05:00.000Z"},
    ]

    with (
        patch("app.routers.dm.resolve_me_id", AsyncMock(return_value="999")),
        patch("app.routers.dm.unlock_and_read_xchat_conversation", AsyncMock(return_value=decrypted)),
    ):
        res = await _enrich_conv_events_with_e2ee(formatted, "a" * 40, "1234", "111-999", max_results=3)

    by_id = {e["id"]: e for e in res["data"]}
    # gql_new must NOT steal opfs_1's text!
    assert by_id["gql_new"]["_xchat_encrypted"] is True
    assert by_id["gql_new"]["text"] == "[XChat E2EE Encrypted Message]"
    # opfs_1 gets its exact match
    assert by_id["opfs_1"]["text"] == "older exact text"
    # With max_results=3, the 3rd slot (extra) must pick the NEWEST timestamped extra,
    # NOT the undated row (which previously sorted FIRST due to reverse=True key inversion).
    assert "opfs_extra_new" in by_id
    assert "nodate_1" not in by_id


# 2. v2_dm_events pagination does NOT re-inject page-1 REST untrusted requests
@pytest.mark.asyncio
async def test_v2_dm_events_paginated_skips_rest_untrusted_requests():
    from app.routers.dm import v2_dm_events

    dm_calls: list[tuple[str, dict]] = []

    async def fake_dm_call(path, tok, params=None, **kw):
        dm_calls.append((path, dict(params or {})))
        return {"status": "ok", "data": {"user_events": {"entries": []}}}

    with (
        patch("app.routers.dm.extract_bearer", return_value="a" * 40),
        patch("app.routers.dm.graphql_call", AsyncMock(return_value={"status": "ok", "data": {"data": {"get_inbox_page": {"items": []}}}})),
        patch("app.routers.dm.dm_call", side_effect=fake_dm_call),
    ):
        await v2_dm_events(
            max_results=20,
            pagination_token="12345|snap1",
            event_types=None,
            dm_event_fields=None,
            expansions=None,
            media_fields=None,
            user_fields=None,
            tweet_fields=None,
            include_requests=1,
            mode="auto",
            authorization="Bearer " + "a" * 40,
            auth_token=None,
            raw=0,
        )

    paths = [p for p, _ in dm_calls]
    assert paths == ["dm/user_updates.json"]


# 3. formatter: GetMessageRequestsPageResponse does not overwrite inbox next_token
def test_formatter_merged_inbox_and_requests_preserves_inbox_next_token():
    from formatter import format_dm_events

    payload = {
        "data": {
            "get_initial_chat_page": {
                "inboxCursor": {"cursor_id": "999", "graph_snapshot_id": "snap_abc"},
                "conversations": [],
            },
            "get_message_requests_page": {
                "__typename": "XChatGetMessageRequestsPageResponse",
                "cursor": {
                    "__typename": "XChatGetMessageRequestsPageContinueCursor",
                    "cursor_id": "req_555",
                    "descending": True,
                },
                "message_request_items": [],
            },
        }
    }
    res = format_dm_events(payload)
    assert res["meta"]["next_token"] == "999|snap_abc"


# 4. formatter: _dm_ts_to_iso normalizes +07:00 and +00:00 ISO strings to UTC Z
def test_dm_ts_to_iso_normalizes_offset_iso_strings():
    from formatter import _dm_ts_to_iso

    assert _dm_ts_to_iso("2026-11-24T17:00:00+07:00") == "2026-11-24T10:00:00.000Z"
    assert _dm_ts_to_iso("2026-11-24T10:00:00.5+00:00") == "2026-11-24T10:00:00.500Z"


# 5. project_dm_entries_to_events preserves media-only and post-link-only OPFS rows
def test_project_dm_entries_keeps_media_only_and_post_link_only():
    from app.xchat_e2ee import project_dm_entries_to_events

    rows = [
        {
            "entry_id": "e_media",
            "timestamp": 1700000001000,
            "sender_id": "111",
            "plain_text": "",
            "has_attachment": 1,
            "attachment_types": "media",
            "deleted": 0,
            "contents": b"",
        },
        {
            "entry_id": "e_link",
            "timestamp": 1700000002000,
            "sender_id": "111",
            "plain_text": "",
            "has_attachment": 1,
            "attachment_types": "link",
            "deleted": 0,
            "contents": b"prefix https://x.com/user/status/1234567890 suffix",
        },
        {
            "entry_id": "e_empty",
            "timestamp": 1700000003000,
            "sender_id": "111",
            "plain_text": "",
            "has_attachment": 0,
            "attachment_types": None,
            "deleted": 0,
            "contents": b"",
        },
    ]
    evs = project_dm_entries_to_events(rows, "111-999", my_user_id="999")
    ids = [e["id"] for e in evs]
    assert "e_media" in ids
    assert "e_link" in ids
    assert "e_empty" not in ids


# 6. BodySizeLimitMiddleware aborts chunked request BEFORE downstream side effects
@pytest.mark.asyncio
async def test_body_size_limit_chunked_aborts_before_side_effects():
    from app.security import BodySizeLimitMiddleware

    side_effect_ran = False
    sent: list[dict] = []

    async def downstream(scope, receive, send):
        nonlocal side_effect_ran
        while True:
            msg = await receive()
            if not msg.get("more_body", False):
                break
        side_effect_ran = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    mw = BodySizeLimitMiddleware(downstream, max_bytes=10)
    chunks = iter([
        {"type": "http.request", "body": b"123456", "more_body": True},
        {"type": "http.request", "body": b"7890123", "more_body": False},
    ])

    async def fake_recv():
        return next(chunks)

    async def fake_send(msg):
        sent.append(msg)

    await mw({"type": "http", "method": "POST", "path": "/2/tweets", "headers": []}, fake_recv, fake_send)
    assert side_effect_ran is False
    assert sent[0]["status"] == 413


# 7. QueryParamSanitizerMiddleware does NOT double-decode %2520 / %25ff, and rejects all-control-char values with 400
@pytest.mark.asyncio
async def test_query_param_sanitizer_no_double_decode_and_rejects_control_only():
    from app.sanitize import QueryParamSanitizerMiddleware

    seen: list[bytes] = []

    async def downstream(scope, receive, send):
        seen.append(scope["query_string"])

    mw = QueryParamSanitizerMiddleware(downstream)

    async def noop(*_a, **_kw):
        return None

    # Literal "100%ff" encoded as "100%25ff" must survive intact!
    scope = {"type": "http", "query_string": b"query=100%25ff&cursor=abc%252Bdef"}
    await mw(scope, noop, noop)
    assert seen == [b"query=100%25ff&cursor=abc%252Bdef"]

    # Non-empty param with only control chars -> 400 Bad Request
    sent: list[dict] = []

    async def cap_send(msg):
        sent.append(msg)

    await mw({"type": "http", "query_string": b"cursor=%00%07"}, noop, cap_send)
    assert sent[0]["status"] == 400


# 8. batch_finalize preserves 401/403 and mixed 5xx instead of mapping to 404
def test_batch_finalize_preserves_401_403_and_mixed_5xx():
    from app.responses import batch_finalize

    r401 = batch_finalize({"data": [], "errors": [{"status": 401, "type": "unauthorized"}]})
    assert r401.status_code == 401
    r403 = batch_finalize({"data": [], "errors": [{"status": 403, "type": "forbidden"}]})
    assert r403.status_code == 403
    r502 = batch_finalize({"data": [], "errors": [{"status": 404}, {"status": 502}]})
    assert r502.status_code == 502


# 9. write_finalize never returns 200 on error status
def test_write_finalize_clamps_200_error_to_502():
    from app.responses import write_finalize

    resp = write_finalize({"status": "error", "http_status": 200, "error": "non-JSON"}, raw=False)
    assert resp.status_code == 502


# 10. _JSONFormatter preserves extra fields in structured JSON logs
def test_json_formatter_includes_extra_fields():
    from app.observability import _JSONFormatter

    fmt = _JSONFormatter()
    rec = logging.LogRecord("xapi.access", logging.INFO, "", 0, "request", (), None)
    rec.method = "GET"
    rec.path = "/health"
    rec.status = 200
    rec.duration_ms = 1.25
    rec.request_id = "abc123"
    parsed = json.loads(fmt.format(rec))
    assert parsed["method"] == "GET"
    assert parsed["path"] == "/health"
    assert parsed["status"] == 200
    assert parsed["request_id"] == "abc123"


# 11. ResponseCache refuses to cache GraphQL error responses with empty data dicts
@pytest.mark.asyncio
async def test_response_cache_skips_errors_with_empty_data_dict():
    from app.response_cache import ResponseCache

    cache = ResponseCache()
    await cache.store(
        "UserByRestId",
        {"userId": "1"},
        "a" * 40,
        {"status": "ok", "data": {"errors": [{"message": "Rate limit"}], "data": {"user": {}}}},
    )
    assert await cache.lookup("UserByRestId", {"userId": "1"}, "a" * 40) is None


# 12. _InFlightCoalescer waiter recovers when owner is cancelled
@pytest.mark.asyncio
async def test_coalescer_waiter_takes_over_on_owner_cancel():
    from playwright_search import _InFlightCoalescer

    c = _InFlightCoalescer()
    started = asyncio.Event()
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await asyncio.sleep(5)
        return {"status": "ok", "call": calls}

    t1 = asyncio.create_task(c.run("k1", fn))
    await started.wait()
    t2 = asyncio.create_task(c.run("k1", fn))
    await asyncio.sleep(0.02)
    t1.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t1
    res2 = await t2
    assert res2 == {"status": "ok", "call": 2}


# 13. v2_user_by_id & v2_users_bulk do not bypass 401 via _cached_profile
@pytest.mark.asyncio
async def test_user_by_id_no_auth_bypass_via_cached_profile():
    from app.routers.users import v2_user_by_id

    with (
        patch("app.routers.users.extract_bearer", return_value="0" * 40),
        patch("app.routers.users.graphql_call", AsyncMock(return_value={"status": "invalid", "http_status": 401, "error": "expired"})),
        patch("app.routers.users._cached_profile", return_value={"id": "123", "username": "secret"}) as mock_cache,
    ):
        resp = await v2_user_by_id("123", authorization="Bearer " + "0" * 40, auth_token=None, raw=0)
    assert resp.status_code == 401
    mock_cache.assert_not_called()


# 14. v2_users_me?raw=1 strips cookies/tokens via wrap() and returns 502 on WarmNetworkError
@pytest.mark.asyncio
async def test_users_me_raw_strips_secrets_and_propagates_502():
    from app.routers.users import v2_users_me

    with (
        patch("app.routers.users.extract_bearer", return_value="a" * 40),
        patch(
            "app.routers.users.login_with_auth_token",
            AsyncMock(return_value={
                "status": "valid",
                "http_status": 200,
                "cookies": {"auth_token": "SECRET", "ct0": "SECRET"},
                "tokens": {"auth_token": "SECRET", "ct0": "SECRET"},
                "user": {"id": "1", "screen_name": "u"},
            }),
        ),
    ):
        resp = await v2_users_me(authorization="Bearer " + "a" * 40, auth_token=None, raw=1)
    body = json.loads(resp.body)
    assert "cookies" not in body
    assert "tokens" not in body

    with (
        patch("app.routers.users.extract_bearer", return_value="a" * 40),
        patch(
            "app.routers.users.login_with_auth_token",
            AsyncMock(return_value={"status": "error", "http_status": 502, "error": "warm failed"}),
        ),
    ):
        resp2 = await v2_users_me(authorization="Bearer " + "a" * 40, auth_token=None, raw=0)
    assert resp2.status_code == 502


# 15. ListMemberBody accepts valid X API v2 body without list_id
def test_list_member_body_accepts_user_id_only():
    from app.routers.lists import ListMemberBody

    b = ListMemberBody(user_id="123456")
    assert b.user_id == "123456"
    assert b.list_id is None


# 16. admin_stats does not crash awaiting synchronous XChatContextPool.stats()
@pytest.mark.asyncio
async def test_admin_stats_calls_sync_xchat_stats_without_await():
    from app.routers.infra import admin_stats

    with (
        patch("app.routers.infra.ADMIN_TOKEN", "secret-admin"),
        patch("app.routers.infra.SessionStore.get") as ss,
        patch("app.routers.infra.TIDProvider.get") as tp,
        patch("app.routers.infra.ClientPool.get") as cp,
        patch("app.routers.infra.ResponseCache.get") as rc,
    ):
        ss.return_value.stats = AsyncMock(return_value={})
        tp.return_value.stats = AsyncMock(return_value={})
        cp.return_value.stats = AsyncMock(return_value={})
        rc.return_value.stats = AsyncMock(return_value={})
        res = await admin_stats(x_admin_token="secret-admin")
    assert "xchat_context_pool" in res
    assert isinstance(res["xchat_context_pool"], dict)


# 17. TIDProvider._refresh browser path acquires PlaywrightPool semaphore
@pytest.mark.asyncio
async def test_tid_provider_browser_fetch_uses_playwright_semaphore():
    from tid_provider import TIDProvider

    sem_events: list[str] = []

    class _FakeSem:
        async def __aenter__(self):
            sem_events.append("enter")
            return self

        async def __aexit__(self, *exc):
            sem_events.append("exit")

    fake_resp = AsyncMock()
    fake_resp.text = AsyncMock(return_value="<html><body>ok</body></html>")
    fake_page = AsyncMock()
    fake_page.goto = AsyncMock(return_value=fake_resp)
    fake_page.close = AsyncMock()
    fake_ctx = AsyncMock()
    fake_ctx.new_page = AsyncMock(return_value=fake_page)

    fake_ctx_pool = MagicMock()
    fake_ctx_pool.acquire = AsyncMock(side_effect=lambda _t: (sem_events.append("acquire"), fake_ctx)[1])
    fake_ctx_pool.release = AsyncMock(side_effect=lambda _t, _c: sem_events.append("release"))

    fake_pw_pool = MagicMock()
    fake_pw_pool.semaphore = _FakeSem()

    tp = TIDProvider()
    with (
        patch("playwright_search.PLAYWRIGHT_ENABLED", True),
        patch("playwright_search.PlaywrightPool.get", return_value=fake_pw_pool),
        patch("playwright_search.ContextPool.get", return_value=fake_ctx_pool),
        patch("tid_provider.get_ondemand_file_url", return_value=None),
        patch("tid_provider._BoundedSession.get", side_effect=RuntimeError("stop after browser")),
    ):
        with pytest.raises(RuntimeError):
            await tp._refresh(auth_token="a" * 40)

    assert sem_events == ["enter", "acquire", "release", "exit"]


# 18. SessionStore.lookup_viewer evicts and returns None when session exceeds MAX_SESSION_AGE_SECONDS
@pytest.mark.asyncio
async def test_session_store_lookup_viewer_respects_session_max_age():
    import time
    from session_cache import MAX_SESSION_AGE_SECONDS, SessionStore

    store = SessionStore()
    tok = "b" * 40
    sess = await store.store(tok, "ct0val", {"auth_token": tok})
    await store.store_viewer(tok, {"id": "123", "username": "alice"})
    assert await store.lookup_viewer(tok) == {"id": "123", "username": "alice"}

    # Age session past MAX_SESSION_AGE_SECONDS while keeping viewer_at fresh
    sess.created_at = time.time() - (MAX_SESSION_AGE_SECONDS + 10)
    sess.viewer_at = time.time()
    assert await store.lookup_viewer(tok) is None
    st = await store.stats()
    assert st["total"] == 0
    assert st["viewer_cached"] == 0


# 19. Bulk tweet & username lookups propagate 401 on invalid token and 502 on http_status=None/200 errors
@pytest.mark.asyncio
async def test_bulk_tweets_and_usernames_normalize_401_and_502():
    from app.routers.tweets import v2_tweets_bulk
    from app.routers.users import v2_users_by_usernames

    with (
        patch("app.routers.tweets.extract_bearer", return_value="a" * 40),
        patch("app.routers.tweets.graphql_call", AsyncMock(return_value={"status": "invalid", "http_status": 200, "error": "expired"})),
    ):
        r1 = await v2_tweets_bulk("12345", authorization="Bearer " + "a" * 40, auth_token=None, raw=0)
    assert r1.status_code == 401

    with (
        patch("app.routers.users.extract_bearer", return_value="a" * 40),
        patch("app.routers.users.graphql_call", AsyncMock(return_value={"status": "error", "http_status": None, "error": "timeout"})),
    ):
        r2 = await v2_users_by_usernames("alice", authorization="Bearer " + "a" * 40, auth_token=None, raw=0)
    assert r2.status_code == 502

    with (
        patch("app.routers.users.extract_bearer", return_value="a" * 40),
        patch("app.routers.users.graphql_call", AsyncMock(return_value={"status": "invalid", "http_status": None, "error": "expired"})),
    ):
        r3 = await v2_users_by_usernames("alice", authorization="Bearer " + "a" * 40, auth_token=None, raw=0)
    assert r3.status_code == 401


# 20. v2_user_by_id clamps 200-error to 502, v2_mentions validates handle, write_finalize maps code 88 to 429
@pytest.mark.asyncio
async def test_user_by_id_clamp_mentions_validation_and_code88_429():
    from app.responses import write_finalize
    from app.routers.users import v2_mentions, v2_user_by_id

    with (
        patch("app.routers.users.extract_bearer", return_value="a" * 40),
        patch("app.routers.users.graphql_call", AsyncMock(return_value={"status": "error", "http_status": 200, "error": "bad"})),
        patch("app.routers.users._cached_profile", return_value=None),
    ):
        r_uid = await v2_user_by_id("12345", authorization="Bearer " + "a" * 40, auth_token=None, raw=0)
    assert r_uid.status_code == 502

    with patch("app.routers.users.extract_bearer", return_value="a" * 40):
        r_bad = await v2_mentions("12345", username="alice OR from:bob", authorization="Bearer " + "a" * 40, auth_token=None, raw=0)
    assert r_bad.status_code == 400

    r_429 = write_finalize(
        {"status": "ok", "data": {"errors": [{"code": 88, "message": "Rate limit exceeded"}], "data": {}}},
        raw=False,
    )
    assert r_429.status_code == 429


# 21. Per-request X-Proxy-Url header middleware, SSRF validation, Playwright conversion, and ClientPool isolation
@pytest.mark.asyncio
async def test_request_proxy_middleware_and_client_pool_isolation():
    from app.client_pool import ClientPool
    from app.config import (
        playwright_proxy_for_token,
        proxy_for_token,
        reset_request_proxy,
        set_request_proxy,
        validate_proxy_url,
    )
    from app.security import RequestProxyMiddleware

    tok = "c" * 40
    captured: list[tuple[Optional[str], Optional[dict]]] = []

    async def downstream(scope, receive, send):
        captured.append((proxy_for_token(tok), playwright_proxy_for_token(tok)))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    mw = RequestProxyMiddleware(downstream)

    async def noop(*_a, **_kw):
        return None

    sent: list[dict] = []

    async def cap_send(msg):
        sent.append(msg)

    # 1. Valid X-Proxy-Url sets proxy inside request & resets cleanly afterward
    scope_proxy = {
        "type": "http",
        "headers": [(b"x-proxy-url", b"http://usr:s%40cret@proxy.example.com:8080")],
    }
    await mw(scope_proxy, noop, cap_send)
    assert sent[0]["status"] == 200
    assert captured[0][0] == "http://usr:s%40cret@proxy.example.com:8080"
    assert captured[0][1] == {
        "server": "http://proxy.example.com:8080",
        "username": "usr",
        "password": "s@cret",
    }
    # After request exits, ContextVar is reset (no leakage to direct callers)
    assert proxy_for_token(tok) is None

    # 2. Direct request (no header) stays direct
    captured.clear()
    sent.clear()
    await mw({"type": "http", "headers": []}, noop, cap_send)
    assert captured[0] == (None, None)

    # 3. Explicit "direct" bypasses PROXY_LIST
    with patch("app.config.PROXY_LIST", ("http://global.example.com:3128",)):
        captured.clear()
        await mw({"type": "http", "headers": [(b"x-proxy-url", b"direct")]}, noop, cap_send)
        assert captured[0] == (None, None)

    # 4. SSRF loopback / invalid scheme rejected with 400 (without echoing password)
    for bad in (b"http://user:topsecret@127.0.0.1:8080", b"http://localhost:3128", b"ftp://proxy.example.com:21"):
        sent.clear()
        await mw({"type": "http", "headers": [(b"x-proxy-url", bad)]}, noop, cap_send)
        assert sent[0]["status"] == 400
        assert b"topsecret" not in sent[1]["body"]

    # 5. ALLOW_REQUEST_PROXY=0 rejects with 403
    with patch("app.security.ALLOW_REQUEST_PROXY", False):
        sent.clear()
        await mw(scope_proxy, noop, cap_send)
        assert sent[0]["status"] == 403

    # 6. ClientPool isolates direct vs proxied sessions for same token & invalidates both
    pool = ClientPool()
    created_kwargs: list[dict] = []

    class _FakeSess:
        async def close(self):
            return None

    def _fake_async_session(**kw):
        created_kwargs.append(kw)
        return _FakeSess()

    with patch("app.client_pool.AsyncSession", side_effect=_fake_async_session):
        s_direct, e_direct = await pool.acquire(tok)
        await pool.release(e_direct)
        ctx_tok = set_request_proxy(validate_proxy_url("http://proxy.example.com:8080"))
        try:
            s_proxy, e_proxy = await pool.acquire(tok)
            await pool.release(e_proxy)
        finally:
            reset_request_proxy(ctx_tok)
        assert s_direct is not s_proxy
        assert "proxies" not in created_kwargs[0]
        assert created_kwargs[1]["proxies"] == {
            "http": "http://proxy.example.com:8080",
            "https": "http://proxy.example.com:8080",
        }
        assert len(pool._cache) == 2
        await pool.invalidate(tok)
        assert len(pool._cache) == 0


# 22. validate_proxy_url rejects IPv4-mapped IPv6 and integer/hex/octal/shorthand loopback IPv4
def test_validate_proxy_url_blocks_obfuscated_ssrf_hosts():
    from app.config import validate_proxy_url

    for bad in (
        "http://[::ffff:127.0.0.1]:8080",
        "http://[::ffff:169.254.169.254]:80",
        "http://2130706433:8080",
        "http://0x7f000001:8080",
        "http://0177.0.0.1:8080",
        "http://127.1:8080",
    ):
        with pytest.raises(ValueError):
            validate_proxy_url(bad)


# 23. SessionStore & Playwright coalescer keys isolate direct vs proxied requests per token
@pytest.mark.asyncio
async def test_session_store_and_coalescer_isolate_proxy_variants():
    from app.config import reset_request_proxy, set_request_proxy, validate_proxy_url
    from playwright_search import _search_key
    from session_cache import SessionStore

    store = SessionStore()
    tok = "d" * 40
    await store.store(tok, "ct0_direct", {"auth_token": tok, "__cf_bm": "direct_cf"})
    key_direct = _search_key(tok, "jkt48", "Latest")

    ctx_tok = set_request_proxy(validate_proxy_url("http://proxy.example.com:8080"))
    try:
        # Must NOT see direct IP-bound session under proxied context
        assert await store.lookup(tok) is None
        await store.store(tok, "ct0_proxy", {"auth_token": tok, "__cf_bm": "proxy_cf"})
        key_proxy = _search_key(tok, "jkt48", "Latest")
        assert (await store.lookup(tok)).cookies["__cf_bm"] == "proxy_cf"
    finally:
        reset_request_proxy(ctx_tok)

    assert key_direct != key_proxy
    assert (await store.lookup(tok)).cookies["__cf_bm"] == "direct_cf"
    assert len(store._cache) == 2
    await store.invalidate(tok)
    assert len(store._cache) == 0


# 24. media_upload falls back to proxy on 403/429/5xx direct failure & v2_dm_media_proxy handles auth/warm errors cleanly
@pytest.mark.asyncio
async def test_media_upload_direct_403_fallback_and_dm_media_proxy_errors():
    from fastapi import HTTPException
    from app.auth import InvalidTokenError, WarmNetworkError
    from app.clients import media_upload
    from app.config import reset_request_proxy, set_request_proxy, validate_proxy_url
    from app.routers.dm import v2_dm_media_proxy

    tok = "e" * 40
    calls: list[str] = []

    class _FakeSess:
        def __init__(self, label):
            self.label = label
            self.cookies = MagicMock()
            self.cookies.jar = []
            self.timeout = 20.0

        async def close(self):
            return None

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_pooled(_t):
        yield _FakeSess("proxy")

    async def _fake_upload(client, *_a, **_kw):
        calls.append(client.label)
        if client.label == "direct":
            return {"status": "error", "http_status": 403, "error": "cf mismatch", "stage": "INIT", "data": None}
        return {"status": "ok", "http_status": 200, "data": {"media_id_string": "999"}}

    ctx_tok = set_request_proxy(validate_proxy_url("http://proxy.example.com:8080"))
    try:
        with (
            patch("app.clients.MEDIA_PROXY_EXEMPT", True),
            patch("app.clients.pooled_client", _fake_pooled),
            patch("app.clients.warm_session", AsyncMock(return_value=("ct0", {}))),
            patch("app.clients._direct_session", return_value=_FakeSess("direct")),
            patch("app.clients._upload_chunks", side_effect=_fake_upload),
        ):
            res = await media_upload(tok, b"jpegbytes", "image/jpeg")
    finally:
        reset_request_proxy(ctx_tok)

    assert res["status"] == "ok"
    assert calls == ["direct", "proxy"]

    # v2_dm_media_proxy requires auth on xchat cached media
    with pytest.raises(HTTPException) as exc_info:
        await v2_dm_media_proxy("xchat", "m1", "img.jpg", authorization=None, auth_token=None)
    assert exc_info.value.status_code == 401

    # v2_dm_media_proxy maps InvalidTokenError -> 401 and WarmNetworkError -> 502 (not 500)
    with (
        patch("app.routers.dm.extract_bearer", return_value=tok),
        patch("app.client_pool.pooled_client", _fake_pooled),
        patch("app.routers.dm.warm_session", AsyncMock(side_effect=InvalidTokenError(401, "expired", {}, ""))),
    ):
        r401 = await v2_dm_media_proxy("123", "456", "img.jpg", authorization="Bearer " + tok, auth_token=None)
    assert r401.status_code == 401

    with (
        patch("app.routers.dm.extract_bearer", return_value=tok),
        patch("app.client_pool.pooled_client", _fake_pooled),
        patch("app.routers.dm.warm_session", AsyncMock(side_effect=WarmNetworkError("proxy down", http_status=502))),
    ):
        r502 = await v2_dm_media_proxy("123", "456", "img.jpg", authorization="Bearer " + tok, auth_token=None)
    assert r502.status_code == 502


# ── 25. Pass 5: validate_proxy_url trailing-dot & IPv6 zone-ID SSRF guards ──

def test_validate_proxy_url_blocks_trailing_dot_and_ipv6_zone_ssrf():
    from app.config import validate_proxy_url

    for bad in (
        "http://localhost.:8080",
        "http://sub.localhost.:8080",
        "http://127.0.0.1.:8080",
        "http://[::1%25lo0]:8080",
        "http://[fe80::1%25eth0]:8080",
        "http://...:8080",
    ):
        with pytest.raises(ValueError):
            validate_proxy_url(bad)


# ── 26. Pass 5: WarmNetworkError 429 preservation & 502 error handling ──

@pytest.mark.asyncio
async def test_pass5_network_error_and_warm_429_preservation():
    from contextlib import asynccontextmanager
    from app.auth import WarmNetworkError, login_with_auth_token
    from app.clients import _dm_call_once, _rest_call_once, media_upload
    from session_cache import SessionStore

    tok = "a" * 40
    await SessionStore.get().invalidate(tok)

    class _ErrClient:
        cookies = MagicMock(jar=[])
        timeout = 20.0
        async def get(self, *a, **kw):
            raise ConnectionResetError("proxy reset")
        async def close(self):
            pass

    @asynccontextmanager
    async def _fake_pooled(_t):
        yield _ErrClient()

    # login_with_auth_token catches viewer GET network errors -> 502 (not 500)
    with (
        patch("app.auth.pooled_client", _fake_pooled),
        patch("app.auth.warm_session", AsyncMock(return_value=("ct0val", {}))),
    ):
        login_res = await login_with_auth_token(tok)
    assert login_res["status"] == "error"
    assert login_res["http_status"] == 502

    # _rest_call_once & _dm_call_once preserve WarmNetworkError(http_status=429)
    with (
        patch("app.clients.pooled_client", _fake_pooled),
        patch("app.clients.warm_session", AsyncMock(side_effect=WarmNetworkError("rate limited", http_status=429))),
    ):
        r_rest = await _rest_call_once("blocks/create.json", tok)
        r_dm = await _dm_call_once("inbox_initial_state.json", tok)
    assert r_rest["http_status"] == 429
    assert r_dm["http_status"] == 429

    # media_upload catches pooled _upload_chunks network error -> 502 (not 500)
    with (
        patch("app.clients.MEDIA_PROXY_EXEMPT", False),
        patch("app.clients.pooled_client", _fake_pooled),
        patch("app.clients.warm_session", AsyncMock(return_value=("ct0val", {}))),
        patch("app.clients._upload_chunks", AsyncMock(side_effect=TimeoutError("proxy timeout"))),
    ):
        up_res = await media_upload(tok, b"abc", "image/jpeg")
    assert up_res["status"] == "error"
    assert up_res["http_status"] == 502


# ── 27. Pass 6: Proxy deep-audit (IPv6 tunnels, canonicalization, dup header, media_upload 401/invalidation, XChat proxy wait) ──

def test_validate_proxy_url_ipv6_tunnels_path_and_canonicalization():
    from app.config import validate_proxy_url

    for bad in (
        "http://[::ffff:0:127.0.0.1]:8080",
        "http://[64:ff9b::127.0.0.1]:8080",
        "http://[2002:7f00:0001::]:8080",
        "http://[::127.0.0.1]:8080",
        "http://31.6.46.27:12323/extra/path",
        "http://31.6.46.27:12323?q=1",
        "http://31.6.46.27:12323#frag",
        "http://127.0.0.1\\@31.6.46.27:12323",
        "http://user:p@ss@31.6.46.27:12323",
    ):
        with pytest.raises(ValueError):
            validate_proxy_url(bad)

    # Canonicalization: uppercase scheme/host and trailing `/` map to the exact same key
    c1 = validate_proxy_url("HTTP://User:Pass@Proxy.Example.COM:8080/")
    c2 = validate_proxy_url("http://User:Pass@proxy.example.com:8080")
    assert c1 == c2 == "http://User:Pass@proxy.example.com:8080"


@pytest.mark.asyncio
async def test_pass6_duplicate_proxy_header_media_401_fallback_and_xchat_wait():
    from contextlib import asynccontextmanager
    from app.clients import media_upload
    from app.config import reset_request_proxy, set_request_proxy
    from app.security import RequestProxyMiddleware
    from playwright_search import XChatContextPool

    # Duplicate conflicting X-Proxy-Url headers -> 400
    captured = []
    async def _dummy_app(scope, receive, send):
        captured.append("called")
    mw = RequestProxyMiddleware(_dummy_app)
    sent = []
    async def _send(msg):
        sent.append(msg)
    scope = {
        "type": "http",
        "headers": [
            (b"x-proxy-url", b"http://1.2.3.4:8080"),
            (b"x-proxy-url", b"http://5.6.7.8:8080"),
        ],
    }
    await mw(scope, AsyncMock(), _send)
    assert not captured
    assert sent[0]["status"] == 400

    # media_upload falls back to proxy on direct 401 AND invalidates on final 403
    tok = "b" * 40
    calls = []
    class _FakeSess:
        def __init__(self, tag):
            self.tag = tag
            self.cookies = MagicMock(jar=[])
            self.timeout = 20.0
        async def close(self):
            pass
    @asynccontextmanager
    async def _fake_pooled(_t):
        yield _FakeSess("proxy")
    async def _fake_upload(sess, *a, **kw):
        calls.append(sess.tag)
        if sess.tag == "direct":
            return {"status": "error", "http_status": 401, "error": "ip mismatch", "stage": "INIT", "data": None}
        return {"status": "error", "http_status": 403, "error": "forbidden", "stage": "INIT", "data": None}

    inv_sess = AsyncMock()
    inv_pool = AsyncMock()
    ctx_tok = set_request_proxy("http://31.6.46.27:12323")
    try:
        with (
            patch("app.clients.MEDIA_PROXY_EXEMPT", True),
            patch("app.clients.pooled_client", _fake_pooled),
            patch("app.clients.warm_session", AsyncMock(return_value=("ct0v", {}))),
            patch("app.clients._direct_session", return_value=_FakeSess("direct")),
            patch("app.clients._upload_chunks", side_effect=_fake_upload),
            patch("app.clients.SessionStore.get", return_value=MagicMock(invalidate=inv_sess)),
            patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=inv_pool)),
        ):
            res = await media_upload(tok, b"img", "image/jpeg")
    finally:
        reset_request_proxy(ctx_tok)
    assert calls == ["direct", "proxy"]
    assert res["http_status"] == 403
    inv_sess.assert_awaited_once_with(tok, all_proxies=False)
    inv_pool.assert_awaited_once_with(tok, all_proxies=False)

    # XChatContextPool waits for in-use context to release before switching proxy
    pool = XChatContextPool()
    old_ctx = MagicMock(pages=[], close=AsyncMock())
    new_ctx = MagicMock(pages=[], add_init_script=AsyncMock(), add_cookies=AsyncMock(), close=AsyncMock())
    import hashlib as _hl
    key = _hl.sha256(f"xchat:{tok}".encode()).hexdigest()[:16]
    pool._ctxs[key] = old_ctx
    pool._ctx_proxy[key] = None  # currently direct
    pool._ctx_use[id(old_ctx)] = 1  # in-use!

    fake_driver = MagicMock()
    fake_driver.chromium.launch_persistent_context = AsyncMock(return_value=new_ctx)
    async def _release_soon():
        await asyncio.sleep(0.05)
        await pool.release(tok, old_ctx)

    ctx_tok2 = set_request_proxy("http://31.6.46.27:12323")
    try:
        with (
            patch("playwright_search.PlaywrightPool.get", return_value=MagicMock(driver=AsyncMock(return_value=fake_driver))),
            patch("playwright_search._apply_session_cookies", AsyncMock()),
        ):
            rel_task = asyncio.create_task(_release_soon())
            got = await pool.acquire(tok)
            await rel_task
    finally:
        reset_request_proxy(ctx_tok2)
    assert got is new_ctx
    old_ctx.close.assert_awaited_once()
    assert pool._ctx_proxy[key] == "http://31.6.46.27:12323"


# ── 28. Pass 7: 0.0.0.0/8, IDNA/control chars, empty port, cred redaction & scoped proxy invalidation ──

@pytest.mark.asyncio
async def test_pass7_proxy_hardening_redaction_and_scoped_invalidation():
    from app.client_pool import ClientPool
    from app.config import redact_proxy_creds, reset_request_proxy, set_request_proxy, validate_proxy_url
    from session_cache import SessionStore

    for bad in (
        "http://0.1.2.3:8080",
        "http://0.0.0.1:8080",
        "http://127\u30020\u30020\u30021:8080",
        "http://\uff11\uff12\uff17.\uff10.\uff10.\uff11:8080",
        "http://31.6.46.27:12323\x0b",
        "http://31.6.46.27:",
        "http://%6c%6f%63%61%6c%68%6f%73%74:8080",
        "http://%31%32%37.0.0.1:8080",
        "http://127.0.0.%31:8080",
        "http://[::ffff:%31%32%37.0.0.1]:8080",
        "http://31.6.46.27:+8080",
        "http://-:8080",
        "http://-a.com:8080",
        "http://a..b.com:8080",
    ):
        with pytest.raises(ValueError):
            validate_proxy_url(bad)

    assert validate_proxy_url("http://31.6.46.27:012323") == "http://31.6.46.27:12323"
    assert validate_proxy_url("https://[2606:4700:0:0::1]:00443/") == "https://[2606:4700::1]:443"

    redacted = redact_proxy_creds("ProxyError: http://myuser:supersecret@31.6.46.27:12323 failed")
    assert "supersecret" not in redacted
    assert "myuser" not in redacted
    assert "http://***@31.6.46.27:12323" in redacted

    redacted_tok = redact_proxy_creds("ProxyError: http://secret_api_key@31.6.46.27:12323 failed")
    assert "secret_api_key" not in redacted_tok
    assert "http://***@31.6.46.27:12323" in redacted_tok

    # warm_session evicts dead ClientPool socket (scoped to active proxy) on double transport failure
    from app.auth import WarmNetworkError, warm_session
    dead_client = MagicMock()
    dead_client.cookies = MagicMock(jar=MagicMock(clear=MagicMock()))
    dead_client.get = AsyncMock(side_effect=ConnectionResetError("proxy http://u:p@31.6.46.27:12323 reset"))
    inv_pool_warm = AsyncMock()
    with (
        patch("app.auth.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None))),
        patch("app.auth.ClientPool.get", return_value=MagicMock(invalidate=inv_pool_warm)),
    ):
        with pytest.raises(WarmNetworkError) as w_exc:
            await warm_session(dead_client, "d" * 40)
    assert "u:p" not in str(w_exc.value)
    inv_pool_warm.assert_awaited_once_with("d" * 40, all_proxies=False)

    # Scoped invalidation (all_proxies=False) only removes the active proxy slot
    tok = "c" * 40
    store = SessionStore()
    await store.store(tok, "ct0_direct", {"auth_token": tok, "ct0": "ct0_direct"})
    t1 = set_request_proxy("http://31.6.46.27:12323")
    try:
        await store.store(tok, "ct0_proxy", {"auth_token": tok, "ct0": "ct0_proxy"})
        await store.invalidate(tok, all_proxies=False)
        assert await store.lookup(tok) is None
    finally:
        reset_request_proxy(t1)
    # Direct session must remain intact after proxy-only 403 invalidation!
    direct_sess = await store.lookup(tok)
    assert direct_sess is not None and direct_sess.ct0 == "ct0_direct"

    # Full invalidation (all_proxies=True, e.g. 401) removes everything
    await store.invalidate(tok, all_proxies=True)
    assert await store.lookup(tok) is None

    # ClientPool scoped invalidation preserves direct entry when proxy entry drops
    cp = ClientPool()
    fake_d = MagicMock(close=AsyncMock())
    fake_p = MagicMock(close=AsyncMock())
    from app.client_pool import _Entry
    cp._cache[cp._pool_key(tok, None)] = _Entry(fake_d)
    cp._cache[cp._pool_key(tok, "http://31.6.46.27:12323")] = _Entry(fake_p)
    t2 = set_request_proxy("http://31.6.46.27:12323")
    try:
        await cp.invalidate(tok, all_proxies=False)
    finally:
        reset_request_proxy(t2)
    assert cp._pool_key(tok, None) in cp._cache
    assert cp._pool_key(tok, "http://31.6.46.27:12323") not in cp._cache
    fake_p.close.assert_awaited_once()
    fake_d.close.assert_not_awaited()


# ── 29. Pass 11: RFC-3696 pseudo-octal/64-bit IPv4 rejection & Playwright goto proxy error handling ──

@pytest.mark.asyncio
async def test_pass11_pseudo_octal_64bit_ipv4_and_browser_proxy_error():
    from app.config import reset_request_proxy, set_request_proxy, validate_proxy_url
    from playwright_search import ContextPool, _search_via_browser_impl

    for bad in (
        "http://127.0.0.08:8080",
        "http://127.0.0.09:8080",
        "http://0.0.0.08:8080",
        "http://169.254.169.0258:80",
        "http://99999999999:8080",
        "http://6425673729:8080",
        "http://0x1000000007f000001:8080",
        "http://127.0.0.0x1:8080",
    ):
        with pytest.raises(ValueError):
            validate_proxy_url(bad)

    # Single-label docker service hostname still allowed
    assert validate_proxy_url("http://squid:3128") == "http://squid:3128"

    # ContextPool scoped invalidation + _search_via_browser_impl goto proxy failure -> 502 + redacted + scoped evict
    tok = "e" * 40
    pool = ContextPool()
    ctx_direct = MagicMock(close=AsyncMock())
    ctx_proxy = MagicMock(close=AsyncMock())
    pool._ctxs[tok] = (ctx_direct, 1.0)
    t = set_request_proxy("http://31.6.46.27:12323")
    try:
        pkey = pool._ctx_key(tok)
        pool._ctxs[pkey] = (ctx_proxy, 1.0)
        await pool.invalidate(tok, all_proxies=False)
        assert pkey not in pool._ctxs
        assert tok in pool._ctxs
        ctx_proxy.close.assert_awaited_once()
        ctx_direct.close.assert_not_awaited()

        fake_page = MagicMock()
        fake_page.on = MagicMock()
        fake_page.goto = AsyncMock(side_effect=RuntimeError("ERR_PROXY_CONNECTION_FAILED http://usr:sec@31.6.46.27:12323"))
        fake_page.close = AsyncMock()
        fake_ctx = MagicMock(new_page=AsyncMock(return_value=fake_page))
        inv_mock = AsyncMock()
        fake_cp = MagicMock(
            acquire=AsyncMock(return_value=fake_ctx),
            release=AsyncMock(),
            invalidate=inv_mock,
        )
        with patch("playwright_search.ContextPool.get", return_value=fake_cp):
            res = await _search_via_browser_impl(tok, "hello", "Latest", timeout=5.0)
    finally:
        reset_request_proxy(t)

    assert res["status"] == "error"
    assert res["http_status"] == 502
    assert "sec" not in res["error"]
    inv_mock.assert_awaited_once_with(tok, all_proxies=False)


# ── 30. Pass 14: warm_session proxy 407/403/402 never misclassified as 401 InvalidTokenError & RFC9110 407->502 mapping ──

@pytest.mark.asyncio
async def test_pass14_warm_session_proxy_407_403_not_401_and_407_mapped_to_502():
    from contextlib import asynccontextmanager
    from app.auth import WarmNetworkError, warm_session
    from app.clients import _rest_call_once, media_upload

    tok = "f" * 40
    # 1. Proxy returning HTTP 407 on GET /home -> WarmNetworkError(502), NOT InvalidTokenError(401)!
    client_407 = MagicMock()
    client_407.cookies = MagicMock(jar=[])
    client_407.cookies.jar = MagicMock(__iter__=lambda self: iter([]), clear=MagicMock())
    client_407.get = AsyncMock(return_value=MagicMock(status_code=407, text="Proxy Auth Required"))
    inv_cp = AsyncMock()
    with (
        patch("app.auth.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None))),
        patch("app.auth.ClientPool.get", return_value=MagicMock(invalidate=inv_cp)),
    ):
        with pytest.raises(WarmNetworkError) as exc_407:
            await warm_session(client_407, tok)
    assert exc_407.value.http_status == 502
    inv_cp.assert_awaited_once_with(tok, all_proxies=False)

    # 2. Cloudflare returning HTTP 403 on GET /home -> WarmNetworkError(403), NOT InvalidTokenError(401)!
    client_403 = MagicMock()
    client_403.cookies = MagicMock()
    client_403.cookies.jar = MagicMock(__iter__=lambda self: iter([]), clear=MagicMock())
    client_403.get = AsyncMock(return_value=MagicMock(status_code=403, text="Just a moment..."))
    with (
        patch("app.auth.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None))),
        patch("app.auth.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
    ):
        with pytest.raises(WarmNetworkError) as exc_403:
            await warm_session(client_403, tok)
    assert exc_403.value.http_status == 403

    # 3. _rest_call_once maps upstream proxy HTTP 407 to 502 and evicts active proxy socket
    sess_407 = MagicMock()
    sess_407.request = AsyncMock(return_value=MagicMock(status_code=407, text="Proxy Auth Required"))
    @asynccontextmanager
    async def _fake_pool(_t):
        yield sess_407
    inv_rest = AsyncMock()
    with (
        patch("app.clients.pooled_client", _fake_pool),
        patch("app.clients.warm_session", AsyncMock(return_value=("ct0v", {}))),
        patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=inv_rest)),
    ):
        r407 = await _rest_call_once("blocks/create.json", tok)
    assert r407["status"] == "error"
    assert r407["http_status"] == 502
    inv_rest.assert_awaited_once_with(tok, all_proxies=False)

    # 4. media_upload falls back to direct warm+upload when proxy warm returns WarmNetworkError(403/502)
    from app.config import reset_request_proxy, set_request_proxy
    t_ctx = set_request_proxy("http://31.6.46.27:12323")
    try:
        warm_calls = []
        async def _fake_warm(sess, _t):
            tag = getattr(sess, "tag", "proxy")
            warm_calls.append(tag)
            if tag == "proxy":
                raise WarmNetworkError("CF 403 on proxy", http_status=403)
            return ("ct0_direct", {"twid": "u%3D1"})
        class _TagSess:
            def __init__(self, tag):
                self.tag = tag
                self.cookies = MagicMock(jar=[])
                self.timeout = 20.0
            async def close(self):
                pass
        @asynccontextmanager
        async def _proxy_pool(_t):
            yield _TagSess("proxy")
        with (
            patch("app.clients.MEDIA_PROXY_EXEMPT", True),
            patch("app.clients.pooled_client", _proxy_pool),
            patch("app.clients.warm_session", side_effect=_fake_warm),
            patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
            patch("app.clients._direct_session", side_effect=lambda *a, **kw: _TagSess("direct")),
            patch("app.clients._upload_chunks", AsyncMock(return_value={"status": "ok", "http_status": 200, "data": {"media_id_string": "99"}})),
        ):
            up = await media_upload(tok, b"img", "image/jpeg")
    finally:
        reset_request_proxy(t_ctx)
    assert up["status"] == "ok"
    assert warm_calls == ["proxy", "direct"]

    # 5. login_with_auth_token: viewer 403 (CF/proxy challenge after valid warm) returns status='error' (403), NOT 'invalid' (401)!
    from app.auth import login_with_auth_token
    v_sess = MagicMock()
    v_sess.cookies = MagicMock(jar=[])
    v_sess.get = AsyncMock(return_value=MagicMock(status_code=403, text="CF Challenge"))
    @asynccontextmanager
    async def _v_pool(_t):
        yield v_sess
    inv_s_v = AsyncMock()
    inv_c_v = AsyncMock()
    with (
        patch("app.auth.SessionStore.get", return_value=MagicMock(lookup_viewer=AsyncMock(return_value=None), invalidate=inv_s_v)),
        patch("app.auth.pooled_client", _v_pool),
        patch("app.auth.warm_session", AsyncMock(return_value=("ct0v", {"twid": "u%3D42"}))),
        patch("app.auth.ClientPool.get", return_value=MagicMock(invalidate=inv_c_v)),
        patch("tid_provider.TIDProvider.get", return_value=MagicMock(generate=AsyncMock(return_value="tid123"))),
    ):
        v_res = await login_with_auth_token(tok)
    assert v_res["status"] == "error"
    assert v_res["http_status"] == 403
    inv_s_v.assert_awaited_once_with(tok, all_proxies=False)
    inv_c_v.assert_awaited_once_with(tok, all_proxies=False)


# ── 31. Pass 18: XChatContextPool SingletonLock race on invalidate-while-in-use & _canon_static_proxy shorthand ──

@pytest.mark.asyncio
async def test_pass18_xchat_singleton_lock_wait_on_dropped_close_and_static_proxy_canon():
    from app.config import _canon_static_proxy
    from playwright_search import XChatContextPool

    assert _canon_static_proxy("31.6.46.27:12323:usr:p@s:s") == "http://usr:p%40s%3As@31.6.46.27:12323"
    assert _canon_static_proxy("http://127.0.0.1:8080") == ""
    assert _canon_static_proxy("direct") == ""

    tok = "9" * 40
    pool = XChatContextPool()
    events_order = []

    async def _slow_close():
        events_order.append("close_start")
        await asyncio.sleep(0.06)
        events_order.append("close_done")

    old_ctx = MagicMock(pages=[], close=AsyncMock(side_effect=_slow_close))
    new_ctx = MagicMock(pages=[], add_init_script=AsyncMock(), add_cookies=AsyncMock(), close=AsyncMock())

    import hashlib as _hl
    key = _hl.sha256(f"xchat:{tok}".encode()).hexdigest()[:16]
    pool._ctxs[key] = old_ctx
    pool._ctx_proxy[key] = "http://31.6.46.27:12323"
    pool._ctx_use[id(old_ctx)] = 1

    # Invalidate while old_ctx is STILL in-use (simulates ERR_PROXY inside xchat_e2ee before finally: release())
    await pool.invalidate(tok)
    assert key not in pool._ctxs
    assert pool._closing_count.get(key) == 1

    async def _launch_new(*a, **kw):
        events_order.append("launch_new")
        return new_ctx

    fake_driver = MagicMock()
    fake_driver.chromium.launch_persistent_context = AsyncMock(side_effect=_launch_new)

    async def _release_holder():
        await asyncio.sleep(0.02)
        await pool.release(tok, old_ctx)

    with (
        patch("playwright_search.PlaywrightPool.get", return_value=MagicMock(driver=AsyncMock(return_value=fake_driver))),
        patch("playwright_search._apply_session_cookies", AsyncMock()),
    ):
        rel_t = asyncio.create_task(_release_holder())
        acquired = await pool.acquire(tok)
        await rel_t

    assert acquired is new_ctx
    # launch_new MUST strictly happen AFTER close_done (never overlapping SingletonLock!)
    assert events_order == ["close_start", "close_done", "launch_new"]


# ── 32. Pass 20: Rotating-proxy __cf_bm GET auto-rewarm, RFC 3986 userinfo/IPv6/brackets, JSON log redaction, browser 401/403/407 eviction, TID proxy, XChat close_all drain ──

@pytest.mark.asyncio
async def test_pass20_proxy_algorithms_rewarm_userinfo_redaction_browser_and_tid():
    import logging
    from contextlib import asynccontextmanager
    from app.auth import InvalidTokenError, WarmNetworkError
    from app.clients import _graphql_call_once, media_upload
    from app.config import (
        normalize_proxy_input,
        redact_proxy_creds,
        reset_request_proxy,
        set_request_proxy,
        validate_proxy_url,
    )
    from app.observability import _JSONFormatter
    from playwright_search import XChatContextPool

    tok = "a" * 40

    # 1. Input normalization + cross-Python (3.9..3.15) bracket/percent validation + uppercase/slash redaction
    assert normalize_proxy_input("http://usr:p[a]ss@31.6.46.27:12323") == "http://usr:p%5Ba%5Dss@31.6.46.27:12323"
    assert validate_proxy_url(normalize_proxy_input("http://usr:p[a]ss@31.6.46.27:12323")) == "http://usr:p%5Ba%5Dss@31.6.46.27:12323"
    assert normalize_proxy_input("http://usr:100%ok%40x@31.6.46.27:12323") == "http://usr:100%25ok%40x@31.6.46.27:12323"
    assert normalize_proxy_input("http://usr:p@s/s#1@31.6.46.27:12323/") == "http://usr:p%40s%2Fs%231@31.6.46.27:12323"
    assert normalize_proxy_input("usr:p[a]s@s@31.6.46.27:12323") == "http://usr:p%5Ba%5Ds%40s@31.6.46.27:12323"
    assert normalize_proxy_input("tok123@31.6.46.27:12323") == "http://tok123@31.6.46.27:12323"
    assert normalize_proxy_input("[2606:4700::1]:8080:u:p@1") == "http://u:p%401@[2606:4700::1]:8080"
    with pytest.raises(ValueError):
        validate_proxy_url("http://usr:p[a]ss@31.6.46.27:12323")
    with pytest.raises(ValueError):
        validate_proxy_url("http://usr:100%zz@31.6.46.27:12323")

    assert redact_proxy_creds("HTTP://usr:p/a@ss@31.6.46.27:12323 and SOCKS5H://tok@1.2.3.4:1080") == (
        "HTTP://***@31.6.46.27:12323 and SOCKS5H://***@1.2.3.4:1080"
    )
    assert redact_proxy_creds("https://x.com/@jack and http://x.com:8080/@jack") == (
        "https://x.com/@jack and http://x.com:8080/@jack"
    )
    rec = logging.LogRecord("xapi.test", logging.WARNING, __file__, 1, "err http://u:secret123@31.6.46.27:12323", (), None)
    rec.proxy_detail = "socks5://u:secret456@31.6.46.27:1080"
    fmt_out = _JSONFormatter().format(rec)
    assert "secret123" not in fmt_out and "secret456" not in fmt_out
    assert "http://***@31.6.46.27:12323" in fmt_out

    # 2. Rotating-proxy __cf_bm / stale cached session auto-rewarm on GraphQL GET:
    #    First call uses cached session -> gets 403 (IP rotated) -> invalidates & rewarms once -> 200 OK!
    gql_calls = 0

    class _RotSess:
        async def get(self, url, headers=None, params=None):
            nonlocal gql_calls
            gql_calls += 1
            if gql_calls == 1:
                return MagicMock(status_code=403, text="CF __cf_bm IP mismatch")
            resp_ok = MagicMock(status_code=200, text='{"data":{"user":{}}}')
            resp_ok.json = MagicMock(return_value={"data": {"user": {"rest_id": "1"}}})
            return resp_ok

    @asynccontextmanager
    async def _rot_pool(_t):
        yield _RotSess()

    lookup_calls = 0

    async def _fake_lookup(_t):
        nonlocal lookup_calls
        lookup_calls += 1
        return ("ct0_cached", {"__cf_bm": "old"}) if lookup_calls == 1 else None

    inv_ss = AsyncMock()
    inv_cp = AsyncMock()
    with (
        patch("app.clients.SessionStore.get", return_value=MagicMock(lookup=_fake_lookup, invalidate=inv_ss)),
        patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=inv_cp)),
        patch("app.clients.pooled_client", _rot_pool),
        patch("app.clients.warm_session", AsyncMock(side_effect=[("ct0_cached", {}), ("ct0_fresh", {})])),
        patch("app.clients.TIDProvider.get", return_value=MagicMock(generate=AsyncMock(return_value="tid"))),
    ):
        gql_res = await _graphql_call_once("UserByRestId", {"userId": "1"}, tok, method="GET")
    assert gql_res["status"] == "ok"
    assert gql_calls == 2
    inv_ss.assert_awaited_once_with(tok, all_proxies=False)

    # 2b. Cached session + revoked token -> GET returns 401 -> rewarm raises InvalidTokenError -> status='invalid' (401)!
    class _RevokedSess:
        async def get(self, url, headers=None, params=None):
            return MagicMock(status_code=401, text='{"errors":[{"code":89}]}')

    @asynccontextmanager
    async def _rev_pool(_t):
        yield _RevokedSess()

    with (
        patch("app.clients.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=("ct0_old", {})), invalidate=AsyncMock())),
        patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
        patch("app.clients.pooled_client", _rev_pool),
        patch("app.clients.warm_session", AsyncMock(side_effect=[("ct0_old", {}), InvalidTokenError(401, "token dead", {}, "ct0")])),
        patch("app.clients.TIDProvider.get", return_value=MagicMock(generate=AsyncMock(return_value="tid"))),
    ):
        rev_res = await _graphql_call_once("UserByRestId", {"userId": "1"}, tok, method="GET")
    assert rev_res["status"] == "invalid"
    assert rev_res["http_status"] == 401

    # 3. media_upload does NOT re-warm dead proxy a second time when proxy_warm_ok is False and direct returns 429
    t_ctx = set_request_proxy("http://31.6.46.27:12323")
    try:
        warm_tags = []

        async def _warm_tag(sess, _t):
            tag = getattr(sess, "tag", "proxy")
            warm_tags.append(tag)
            if tag == "proxy":
                raise WarmNetworkError("proxy timeout", http_status=502)
            return ("ct0_d", {"twid": "u%3D1"})

        class _TS:
            def __init__(self, tag):
                self.tag = tag
                self.cookies = MagicMock(jar=[])
                self.timeout = 20.0
            async def close(self):
                pass

        @asynccontextmanager
        async def _p_pool(_t):
            yield _TS("proxy")

        with (
            patch("app.clients.MEDIA_PROXY_EXEMPT", True),
            patch("app.clients.pooled_client", _p_pool),
            patch("app.clients.warm_session", side_effect=_warm_tag),
            patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
            patch("app.clients._direct_session", side_effect=lambda *a, **kw: _TS("direct")),
            patch("app.clients._upload_chunks", AsyncMock(return_value={"status": "error", "http_status": 429, "error": "rate limit", "data": None})),
        ):
            m_res = await media_upload(tok, b"img", "image/jpeg")
    finally:
        reset_request_proxy(t_ctx)
    assert m_res["http_status"] == 429
    assert warm_tags == ["proxy", "direct"]

    # 4. XChatContextPool.close_all holds _closing_count until ctx.close() completes (even for dropped in-use contexts)
    xpool = XChatContextPool()
    order_close = []

    async def _slow_c():
        order_close.append("closing_start")
        await asyncio.sleep(0.05)
        order_close.append("closing_end")

    d_ctx = MagicMock(pages=[], close=AsyncMock(side_effect=_slow_c))
    n_ctx = MagicMock(pages=[], add_init_script=AsyncMock(), add_cookies=AsyncMock(), close=AsyncMock())
    import hashlib as _hl
    xkey = _hl.sha256(f"xchat:{tok}".encode()).hexdigest()[:16]
    xpool._ctxs[xkey] = d_ctx
    xpool._ctx_keys[id(d_ctx)] = xkey
    xpool._ctx_use[id(d_ctx)] = 1
    await xpool.invalidate(tok)  # moves d_ctx into _dropped

    async def _mk_ctx(*a, **kw):
        order_close.append("launch_after_close_all")
        return n_ctx

    f_drv = MagicMock()
    f_drv.chromium.launch_persistent_context = AsyncMock(side_effect=_mk_ctx)
    with (
        patch("playwright_search.PlaywrightPool.get", return_value=MagicMock(driver=AsyncMock(return_value=f_drv))),
        patch("playwright_search._apply_session_cookies", AsyncMock()),
    ):
        t_close_all = asyncio.create_task(xpool.close_all())
        await asyncio.sleep(0.01)
        got_ctx = await xpool.acquire(tok)
        await t_close_all
    assert got_ctx is n_ctx
    assert order_close == ["closing_start", "closing_end", "launch_after_close_all"]

    # 5. v2_dm_media_proxy retries cached-session 403 once (rotating proxy recovery) and maps 407 -> 502 consistently
    from app.routers.dm import v2_dm_media_proxy
    ton_calls = 0

    class _TonSess:
        def __init__(self):
            self.cookies = MagicMock()
        async def get(self, url, headers=None):
            nonlocal ton_calls
            ton_calls += 1
            if ton_calls == 1:
                return MagicMock(status_code=403, text="CF mismatch", headers={})
            return MagicMock(status_code=200, content=b"JPGDATA", headers={"content-type": "image/jpeg"})

    @asynccontextmanager
    async def _ton_pool(_t):
        yield _TonSess()

    ton_lks = 0
    async def _ton_lk(_t):
        nonlocal ton_lks
        ton_lks += 1
        return ("ct0_c", {}) if ton_lks == 1 else None

    with (
        patch("app.routers.dm.SessionStore.get", return_value=MagicMock(lookup=_ton_lk, invalidate=AsyncMock())),
        patch("app.client_pool.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
        patch("app.client_pool.pooled_client", _ton_pool),
        patch("app.routers.dm.warm_session", AsyncMock(side_effect=[("ct0_c", {}), ("ct0_f", {})])),
    ):
        ton_resp = await v2_dm_media_proxy("111", "222", "img.jpg", authorization=f"Bearer {tok}", auth_token=None)
    assert ton_resp.status_code == 200
    assert ton_resp.body == b"JPGDATA"
    assert ton_calls == 2

    class _Ton407Sess:
        def __init__(self):
            self.cookies = MagicMock()
        async def get(self, url, headers=None):
            return MagicMock(status_code=407, text="Proxy Auth Required", headers={})

    @asynccontextmanager
    async def _ton407_pool(_t):
        yield _Ton407Sess()

    with (
        patch("app.routers.dm.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None), invalidate=AsyncMock())),
        patch("app.client_pool.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
        patch("app.client_pool.pooled_client", _ton407_pool),
        patch("app.routers.dm.warm_session", AsyncMock(return_value=("ct0_f", {}))),
    ):
        ton_407 = await v2_dm_media_proxy("111", "222", "img.jpg", authorization=f"Bearer {tok}", auth_token=None)
    assert ton_407.status_code == 502
    assert b'"status":502' in ton_407.body or b'"status": 502' in ton_407.body
