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


# ── 33. Pass 22: _direct_session strips __cf_bm, no_retry on 407/double-warm, ResponseCache 401 eviction, Playwright goto>=400 fail-fast & TID browser status check ──

@pytest.mark.asyncio
async def test_pass22_cf_cookie_strip_no_retry_407_response_cache_401_and_browser_nav_status(monkeypatch):
    from contextlib import asynccontextmanager
    from app.auth import InvalidTokenError, warm_session
    from app.clients import _direct_session, graphql_call, media_upload
    from app.config import normalize_proxy_input
    from app.response_cache import ResponseCache
    from playwright_search import ContextPool, _search_via_browser_impl
    from tid_provider import TIDProvider

    tok = "b" * 40

    # 1. Uppercase scheme normalization & _direct_session strips proxy IP-bound Cloudflare cookies
    assert normalize_proxy_input("HTTP://usr:pass@31.6.46.27:12323") == "http://usr:pass@31.6.46.27:12323"
    ds = _direct_session(
        tok,
        {"twid": "u%3D1", "__cf_bm": "proxy_ip_bound", "_cfuvid": "uv1", "cf_clearance": "cfc", "kdt": "keepme"},
        10.0,
    )
    try:
        jar_names = {c.name for c in ds.cookies.jar}
        assert "twid" in jar_names and "kdt" in jar_names
        assert "__cf_bm" not in jar_names and "_cfuvid" not in jar_names and "cf_clearance" not in jar_names
    finally:
        await ds.close()

    # 2. graphql_call (with_retry) does NOT retry 3x when proxy returns 407 or warm_session failed twice
    attempts_407 = 0

    class _Proxy407Sess:
        async def get(self, url, headers=None, params=None):
            nonlocal attempts_407
            attempts_407 += 1
            return MagicMock(status_code=407, text="Proxy Auth Required")

    @asynccontextmanager
    async def _p407_pool(_t):
        yield _Proxy407Sess()

    with (
        patch("app.clients.ResponseCache.get", return_value=MagicMock(lookup=AsyncMock(return_value=None), store=AsyncMock())),
        patch("app.clients.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None), invalidate=AsyncMock())),
        patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
        patch("app.clients.pooled_client", _p407_pool),
        patch("app.clients.warm_session", AsyncMock(return_value=("ct0v", {}))),
        patch("app.clients.TIDProvider.get", return_value=MagicMock(generate=AsyncMock(return_value="tid"))),
    ):
        r_no_retry = await graphql_call("UserByRestId", {"userId": "1"}, tok)
    assert r_no_retry["http_status"] == 502
    assert "_no_retry" not in r_no_retry
    assert attempts_407 == 1  # Never hammered 3x on 407!

    # 2b. warm_session double network failure sets no_retry=True so graphql_call doesn't multiply 2x into 6x
    dead_home_calls = 0

    class _DeadProxySess:
        def __init__(self):
            self.cookies = MagicMock()
            self.cookies.jar = MagicMock(__iter__=lambda self: iter([]), clear=MagicMock())
        async def get(self, url, **kw):
            nonlocal dead_home_calls
            dead_home_calls += 1
            raise ConnectionError("proxy unreachable")

    @asynccontextmanager
    async def _dead_pool(_t):
        yield _DeadProxySess()

    with (
        patch("app.clients.ResponseCache.get", return_value=MagicMock(lookup=AsyncMock(return_value=None), store=AsyncMock())),
        patch("app.auth.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None))),
        patch("app.auth.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
        patch("app.clients.pooled_client", _dead_pool),
    ):
        r_dead = await graphql_call("UserByRestId", {"userId": "1"}, tok)
    assert r_dead["http_status"] == 502
    assert dead_home_calls == 2  # Exactly 2 attempts in warm_session, NOT 6!

    # 3. ResponseCache evicts cached responses for token on 401
    rc = ResponseCache()
    await rc.store("UserByRestId", {"userId": "1"}, tok, {"status": "ok", "data": {"data": {"user": {"id": "1"}}}})
    assert (await rc.lookup("UserByRestId", {"userId": "1"}, tok)) is not None
    rc.invalidate_token(tok)
    assert (await rc.lookup("UserByRestId", {"userId": "1"}, tok)) is None

    # 4. Playwright _search_via_browser_impl fails fast (0s, no 20s hang) & evicts ContextPool when page.goto returns HTTP 407
    fake_page = MagicMock()
    fake_page.on = MagicMock()
    fake_page.goto = AsyncMock(return_value=MagicMock(status=407))
    fake_page.close = AsyncMock()
    fake_ctx = MagicMock(new_page=AsyncMock(return_value=fake_page))
    inv_ctx = AsyncMock()
    with patch(
        "playwright_search.ContextPool.get",
        return_value=MagicMock(acquire=AsyncMock(return_value=fake_ctx), invalidate=inv_ctx, release=AsyncMock()),
    ):
        pw_407 = await _search_via_browser_impl(tok, "jkt48", "Latest", timeout=20.0)
    assert pw_407["status"] == "error"
    assert pw_407["http_status"] == 502
    inv_ctx.assert_awaited_once_with(tok, all_proxies=False)

    # 5. ContextPool.close_all closes _dropped contexts too
    cpool = ContextPool()
    dropped_ctx = MagicMock(close=AsyncMock())
    active_ctx = MagicMock(close=AsyncMock())
    cpool._ctxs[tok] = (active_ctx, 1.0)
    cpool._dropped.add(dropped_ctx)
    await cpool.close_all()
    active_ctx.close.assert_awaited_once()
    dropped_ctx.close.assert_awaited_once()
    assert len(cpool._dropped) == 0

    # 6. TIDProvider._refresh ignores non-200 browser page.goto (e.g. 403/407) and falls back cleanly
    import playwright_search as _pws
    monkeypatch.setattr(_pws, "PLAYWRIGHT_ENABLED", True)
    tid_page = MagicMock(goto=AsyncMock(return_value=MagicMock(status=407)), close=AsyncMock())
    tid_ctx = MagicMock(new_page=AsyncMock(return_value=tid_page))
    tid_inv = AsyncMock()
    tp = TIDProvider()
    with (
        patch("playwright_search.PlaywrightPool.get", return_value=MagicMock(semaphore=asyncio.Semaphore(1))),
        patch("playwright_search.ContextPool.get", return_value=MagicMock(acquire=AsyncMock(return_value=tid_ctx), invalidate=tid_inv, release=AsyncMock())),
        patch("tid_provider.ClientTransaction", return_value="FAKE_CT"),
        patch.object(tp, "_is_stale", return_value=True),
    ):
        # Mock curl_cffi fallback inside _refresh by patching AsyncSession
        fake_cffi = MagicMock()
        fake_cffi.get = AsyncMock(return_value=MagicMock(status_code=200, text="<html><script src='https://abs.twimg.com/responsive-web/client-web/ondemand.s.1234abcda.js'></script></html>"))
        fake_cffi.close = AsyncMock()
        with (
            patch("curl_cffi.requests.AsyncSession", return_value=fake_cffi),
            patch("tid_provider._BoundedSession") as mock_bs,
        ):
            sess_inst = MagicMock()
            sess_inst.__enter__.return_value = sess_inst
            sess_inst.get.return_value = MagicMock(
                status_code=200,
                text="https://abs.twimg.com/responsive-web/client-web/ondemand.s.1234abcda.js",
                content=b"console.log(1)",
                raise_for_status=MagicMock(),
            )
            mock_bs.return_value = sess_inst
            await tp._refresh(tok)
    assert tp._ct == "FAKE_CT"
    tid_inv.assert_awaited_once_with(tok, all_proxies=False)


# ── 34. Pass 24: Adversarial fuzzer fixes (shorthand/quote/spaceless redaction, cloud metadata & NAT64 local-use SSRF, host/port canonicalization) ──

def test_pass24_fuzzer_redaction_cloud_metadata_ssrf_and_hostport_canon():
    from app.config import normalize_proxy_input, redact_proxy_creds, validate_proxy_url

    # 1. Shorthand host:port:user:pass, [ipv6]:port:user:pass, quotes/<> in password, and spaceless multi-URL redaction
    assert redact_proxy_creds("err 31.6.46.27:08080:user:secretpass ok") == "err 31.6.46.27:08080:*** ok"
    assert redact_proxy_creds("err [2606:4700::1]:8080:user:secret:pass ok") == "err [2606:4700::1]:8080:*** ok"
    assert "secret" not in redact_proxy_creds("http://user:s'ec\"re<t>@31.6.46.27:12323")
    assert redact_proxy_creds("target=http://foo:bar/baz,proxy=http://user:secret@31.6.46.27:12323") == (
        "target=http://foo:bar/baz,proxy=http://***@31.6.46.27:12323"
    )

    # 2. Cloud metadata hostnames & RFC 8215 local-use NAT64 / SIIT loopback blocked
    for bad in (
        "http://metadata.google.internal:80",
        "http://metadata.goog:80",
        "http://metadata.azure.internal:80",
        "http://instance-data.ec2.internal:80",
        "http://[64:ff9b:1::127.0.0.1]:8080",
        "http://[64:ff9b:1::169.254.169.254]:80",
        "http://[::ffff:0:169.254.169.254]:80",
    ):
        with pytest.raises(ValueError):
            validate_proxy_url(bad)

    # 3. Leading-zero port and uppercase trailing-dot host canonicalized identically
    assert normalize_proxy_input("31.6.46.27:08080:user:pass") == "http://user:pass@31.6.46.27:8080"
    assert normalize_proxy_input("[2606:4700::ABCD]:08080:user:pass") == "http://user:pass@[2606:4700::abcd]:8080"
    assert normalize_proxy_input("http://user:pass@EXAMPLE.COM.:08080/") == "http://user:pass@example.com:8080"


# ── 35. Pass 26: XChat page.goto>=400 eviction, schemeless user:pass@host:port redaction, & TID captive-portal HTML rejection ──

@pytest.mark.asyncio
async def test_pass26_xchat_nav_407_eviction_schemeless_at_redaction_and_tid_captive_portal(monkeypatch):
    from app.config import redact_proxy_creds
    from app.xchat_e2ee import send_xchat_dm_via_browser, unlock_and_read_xchat_inbox
    from tid_provider import TIDProvider

    tok = "c" * 40

    # 1. Schemeless user:pass@host:port & user:pass@[ipv6]:port redacted without touching emails
    assert redact_proxy_creds("err usr:secretpass@31.6.46.27:12323 and usr:sec2@[2606:4700::1]:8080") == (
        "err ***@31.6.46.27:12323 and ***@[2606:4700::1]:8080"
    )
    assert redact_proxy_creds("contact alice@example.com") == "contact alice@example.com"

    # 2. XChat inbox & send_xchat_dm_via_browser evict XChatContextPool immediately on HTTP 407 page.goto
    x_page = MagicMock(goto=AsyncMock(return_value=MagicMock(status=407)), close=AsyncMock())
    x_ctx = MagicMock(new_page=AsyncMock(return_value=x_page))
    x_inv = AsyncMock()
    with (
        patch("app.xchat_e2ee.PlaywrightPool.get", return_value=MagicMock(semaphore=asyncio.Semaphore(1))),
        patch("app.xchat_e2ee.XChatContextPool.get", return_value=MagicMock(acquire=AsyncMock(return_value=x_ctx), invalidate=x_inv, release=AsyncMock())),
    ):
        inbox_res = await unlock_and_read_xchat_inbox(tok, "1234", my_user_id="1")
        send_res = await send_xchat_dm_via_browser(tok, "1234", "1-2", "hi")
    assert inbox_res == []
    assert send_res["status"] == "error"
    assert send_res["http_status"] == 502
    assert x_inv.await_count == 2

    # 3. TIDProvider skips proxy captive-portal 200 HTML missing X shell markers and falls back to requests
    import playwright_search as _pws
    monkeypatch.setattr(_pws, "PLAYWRIGHT_ENABLED", False)
    tp = TIDProvider()
    captive_cffi = MagicMock()
    captive_cffi.get = AsyncMock(return_value=MagicMock(status_code=200, text="<html><body>Captive Portal Login</body></html>"))
    captive_cffi.close = AsyncMock()
    with (
        patch("curl_cffi.requests.AsyncSession", return_value=captive_cffi),
        patch("tid_provider.handle_x_migration", return_value="<html><svg id='loading-x-anim-0'></svg></html>"),
        patch("tid_provider.ClientTransaction", return_value="CT_AFTER_CAPTIVE"),
        patch("tid_provider._BoundedSession") as mock_bs,
    ):
        sess_inst = MagicMock()
        sess_inst.__enter__.return_value = sess_inst
        sess_inst.get.return_value = MagicMock(
            status_code=200,
            text="https://abs.twimg.com/responsive-web/client-web/ondemand.s.1234abcda.js",
            content=b"console.log(1)",
            raise_for_status=MagicMock(),
        )
        mock_bs.return_value = sess_inst
        await tp._refresh(tok)
    assert tp._ct == "CT_AFTER_CAPTIVE"


# ── 36. Pass 28: DM resolve_me_id WarmNetworkError (no false 401), strict userinfo `;`/quote validation, & fetch_dm_pin._download_ton ──

@pytest.mark.asyncio
async def test_pass28_dm_resolve_me_warm_error_no_false_401_userinfo_semicolon_and_ton_cli():
    from contextlib import asynccontextmanager
    from app.auth import InvalidTokenError, WarmNetworkError
    from app.config import normalize_proxy_input, validate_proxy_url
    from app.response_cache import ResponseCache
    from app.routers.dm import DMSendBody, v2_dm_block, v2_dm_send, v2_dm_send_to_conv, v2_dm_with_user_events
    import fetch_dm_pin

    tok = "d" * 40

    # 1. Strict RFC 3986 userinfo charset rejects raw `;` (Python <3.12 vs 3.12+ divergence), quotes, and `<>`,
    #    while normalize_proxy_input encodes them cleanly and canonicalizes %XX hex + uncompressed IPv6.
    for bad_ui in (
        "http://user:p;ass@31.6.46.27:12323",
        "http://user:p'ass@31.6.46.27:12323",
        'http://user:p"ass@31.6.46.27:12323',
        "http://user:p<ass>@31.6.46.27:12323",
    ):
        with pytest.raises(ValueError):
            validate_proxy_url(bad_ui)
    assert validate_proxy_url(normalize_proxy_input("http://user:p;ass@31.6.46.27:12323")) == (
        "http://user:p%3Bass@31.6.46.27:12323"
    )
    assert validate_proxy_url("http://user:p%3ass@31.6.46.27:12323") == "http://user:p%3Ass@31.6.46.27:12323"
    assert normalize_proxy_input("[2606:4700:0:0::ABCD]:08080:user:pass") == "http://user:pass@[2606:4700::abcd]:8080"

    # 2. Proxy WarmNetworkError inside resolve_me_id MUST return 502/429 (NEVER false 401 Unauthorized!) across DM routes
    @asynccontextmanager
    async def _warm_err_pool(_t):
        yield MagicMock()

    with (
        patch("app.auth.pooled_client", _warm_err_pool),
        patch("app.auth.warm_session", AsyncMock(side_effect=WarmNetworkError("proxy 407 auth failed", http_status=502))),
    ):
        r_send = await v2_dm_send(participant_id="222", body=DMSendBody(text="hi"), dm_pin=None, x_dm_pin=None, authorization=f"Bearer {tok}", auth_token=None, raw=0)
        r_hist = await v2_dm_with_user_events(
            participant_id="222", max_results=10, pagination_token=None, event_types=None,
            dm_event_fields=None, expansions=None, media_fields=None, user_fields=None,
            tweet_fields=None, mode="auto", dm_pin=None, x_dm_pin=None,
            authorization=f"Bearer {tok}", auth_token=None, raw=0,
        )
        r_blk = await v2_dm_block(user_id="222", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_send.status_code == 502
    assert r_hist.status_code == 502
    assert r_blk.status_code == 502

    with (
        patch("app.auth.pooled_client", _warm_err_pool),
        patch("app.auth.warm_session", AsyncMock(side_effect=WarmNetworkError("rate limited", http_status=429))),
    ):
        r_429 = await v2_dm_with_user_events(
            participant_id="222", max_results=10, pagination_token=None, event_types=None,
            dm_event_fields=None, expansions=None, media_fields=None, user_fields=None,
            tweet_fields=None, mode="auto", dm_pin=None, x_dm_pin=None,
            authorization=f"Bearer {tok}", auth_token=None, raw=0,
        )
    assert r_429.status_code == 429

    # 2b. v2_dm_send_to_conv falls back to send_xchat_dm_via_browser when dm_pin is present and resolve_me_id hits WarmNetworkError
    with (
        patch("app.auth.pooled_client", _warm_err_pool),
        patch("app.auth.warm_session", AsyncMock(side_effect=WarmNetworkError("CF 403 on proxy", http_status=403))),
        patch("app.routers.dm.send_xchat_dm_via_browser", AsyncMock(return_value={"status": "ok", "data": {"dm_event_id": "e2ee_1"}})),
    ):
        r_conv_e2ee = await v2_dm_send_to_conv(
            conversation_id="111-222", body=DMSendBody(text="hi"), dm_pin=None,
            x_dm_pin="1234", authorization=f"Bearer {tok}", auth_token=None, raw=0,
        )
    assert r_conv_e2ee.status_code == 201

    # 2c. Genuine InvalidTokenError still returns 401 AND evicts ResponseCache
    rc = ResponseCache.get()
    await rc.store("UserByRestId", {"userId": "99"}, tok, {"status": "ok", "data": {"data": {"user": {"id": "99"}}}})
    with (
        patch("app.auth.pooled_client", _warm_err_pool),
        patch("app.auth.warm_session", AsyncMock(side_effect=InvalidTokenError(401, "expired", {}, ""))),
    ):
        r_401 = await v2_dm_block(user_id="222", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_401.status_code == 401
    assert (await rc.lookup("UserByRestId", {"userId": "99"}, tok)) is None

    # 3. fetch_dm_pin._download_ton auto-rewarms on cached 403 & redacts proxy credentials on transport failure
    ton_calls = 0

    class _CliTonSess:
        def __init__(self):
            self.cookies = MagicMock()
        async def get(self, url, headers=None):
            nonlocal ton_calls
            ton_calls += 1
            if ton_calls == 1:
                return MagicMock(status_code=403, headers={})
            return MagicMock(status_code=200, content=b"IMGBYTES", headers={"content-type": "image/png"})

    @asynccontextmanager
    async def _cli_ton_pool(_t):
        yield _CliTonSess()

    cli_lks = 0
    async def _cli_lk(_t):
        nonlocal cli_lks
        cli_lks += 1
        return ("ct0_c", {}) if cli_lks == 1 else None

    with (
        patch.object(fetch_dm_pin.SessionStore, "get", return_value=MagicMock(lookup=_cli_lk, invalidate=AsyncMock())),
        patch.object(fetch_dm_pin.ClientPool, "get", return_value=MagicMock(invalidate=AsyncMock())),
        patch.object(fetch_dm_pin, "pooled_client", _cli_ton_pool),
        patch.object(fetch_dm_pin, "warm_session", AsyncMock(side_effect=[("ct0_c", {"twid": "u%3D1"}), ("ct0_f", {"twid": "u%3D1"})])),
    ):
        data_ok, mime_ok = await fetch_dm_pin._download_ton(tok, "https://ton.x.com/1.1/ton/data/dm/1/2/a.png")
    assert data_ok == b"IMGBYTES"
    assert mime_ok == "image/png"
    assert ton_calls == 2

    class _CliErrSess:
        def __init__(self):
            self.cookies = MagicMock()
        async def get(self, url, headers=None):
            raise ConnectionError("connect via http://usr:topsecret@31.6.46.27:12323 failed")

    @asynccontextmanager
    async def _cli_err_pool(_t):
        yield _CliErrSess()

    with (
        patch.object(fetch_dm_pin.SessionStore, "get", return_value=MagicMock(lookup=AsyncMock(return_value=None), invalidate=AsyncMock())),
        patch.object(fetch_dm_pin.ClientPool, "get", return_value=MagicMock(invalidate=AsyncMock())),
        patch.object(fetch_dm_pin, "pooled_client", _cli_err_pool),
        patch.object(fetch_dm_pin, "warm_session", AsyncMock(return_value=("ct0_f", {}))),
    ):
        data_err, reason_err = await fetch_dm_pin._download_ton(tok, "https://ton.x.com/1.1/ton/data/dm/1/2/a.png")
    assert data_err is None
    assert "topsecret" not in reason_err
    assert "***@31.6.46.27:12323" in reason_err


# ── 37. Pass 31: TID handle_x_migration 407/captive fallback, SearchTimeline POST rewarm, media_upload post-exempt rewarm, & Playwright 401/search fallback ──

@pytest.mark.asyncio
async def test_pass31_tid_migration_407_fallback_search_post_rewarm_upload_rewarm_and_pw_401(monkeypatch):
    from contextlib import asynccontextmanager
    from app.clients import graphql_call, media_upload
    from app.config import reset_request_proxy, set_request_proxy, validate_proxy_url
    from app.response_cache import ResponseCache
    from app.routers.tweets import v2_tweets_search_recent
    from playwright_search import _action_via_browser_impl
    from tid_provider import TIDProvider
    import playwright_search as _pws

    tok = "e" * 40

    # 1. TIDProvider._refresh detects HTTP 407 / captive HTML inside handle_x_migration via proxy and falls back to direct
    monkeypatch.setattr(_pws, "PLAYWRIGHT_ENABLED", False)
    tp = TIDProvider()
    ctx_tok = set_request_proxy(validate_proxy_url("http://usr:secret@31.6.46.27:12323"))
    try:
        dead_cffi = MagicMock(get=AsyncMock(return_value=MagicMock(status_code=407, text="Proxy Auth")), close=AsyncMock())
        bs_proxies_seen = []

        def _make_bs():
            inst = MagicMock()
            inst.__enter__.return_value = inst
            inst.proxies = {}
            def _req(*a, **kw):
                bs_proxies_seen.append(dict(inst.proxies))
                if inst.proxies:
                    return MagicMock(status_code=407, content=b"<html>Proxy Auth Required</html>")
                return MagicMock(status_code=200, content=b"<html><svg id='loading-x-anim-0'></svg></html>")
            inst.request = _req
            def _get(url, **kw):
                if inst.proxies:
                    return MagicMock(status_code=200, content=b"<html>Captive Portal</html>", text="")
                return MagicMock(
                    status_code=200,
                    text="https://abs.twimg.com/responsive-web/client-web/ondemand.s.1234abcda.js",
                    content=b"console.log('real js')",
                )
            inst.get = _get
            return inst

        with (
            patch("curl_cffi.requests.AsyncSession", return_value=dead_cffi),
            patch("tid_provider._BoundedSession", side_effect=_make_bs),
            patch("tid_provider.ClientTransaction", return_value="CT_DIRECT_OK"),
        ):
            await tp._refresh(tok)
        assert tp._ct == "CT_DIRECT_OK"
        assert any(p for p in bs_proxies_seen) and any(not p for p in bs_proxies_seen)
    finally:
        reset_request_proxy(ctx_tok)

    # 2. SearchTimeline (POST read-only query) performs 1x rotating-proxy auto-rewarm on cached 403
    st_calls = 0

    class _SearchRotSess:
        async def post(self, url, headers=None, json=None):
            nonlocal st_calls
            st_calls += 1
            if st_calls == 1:
                return MagicMock(status_code=403, text="CF IP changed")
            return MagicMock(status_code=200, json=lambda: {"data": {"search_by_raw_query": {"search_timeline": {"timeline": {"instructions": []}}}}})

    @asynccontextmanager
    async def _search_pool(_t):
        yield _SearchRotSess()

    st_lks = 0
    async def _st_lk(_t):
        nonlocal st_lks
        st_lks += 1
        return ("ct0_c", {}) if st_lks == 1 else None

    with (
        patch("app.clients.ResponseCache.get", return_value=MagicMock(lookup=AsyncMock(return_value=None), store=AsyncMock())),
        patch("app.clients.SessionStore.get", return_value=MagicMock(lookup=_st_lk, invalidate=AsyncMock())),
        patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
        patch("app.clients.pooled_client", _search_pool),
        patch("app.clients.warm_session", AsyncMock(side_effect=[("ct0_c", {}), ("ct0_f", {})])),
        patch("app.clients.TIDProvider.get", return_value=MagicMock(generate=AsyncMock(return_value="tid"))),
    ):
        r_search = await graphql_call("SearchTimeline", {"rawQuery": "jkt48", "count": 5, "product": "Latest"}, tok, method="POST")
    assert r_search["status"] == "ok"
    assert st_calls == 2

    # 3. media_upload rewarms proxy session on INIT 403 even when SessionStore was populated during initial warm before MEDIA_PROXY_EXEMPT direct fallback
    ctx_tok2 = set_request_proxy(validate_proxy_url("http://31.6.46.27:12323"))
    try:
        up_lks = 0
        async def _up_lk(_t):
            nonlocal up_lks
            up_lks += 1
            # 1st lookup (before initial warm) -> None; 2nd lookup (before proxy INIT attempt 0) -> cached!
            return None if up_lks == 1 else ("ct0_warm1", {"twid": "u%3D1"})

        proxy_init_calls = 0

        class _UpProxySess:
            timeout = 20.0
            def __init__(self):
                self.cookies = MagicMock()
                self.cookies.jar = []
            async def post(self, url, headers=None, data=None, multipart=None):
                nonlocal proxy_init_calls
                cmd = (data or {}).get("command")
                if cmd == "INIT":
                    proxy_init_calls += 1
                    if proxy_init_calls == 1:
                        return MagicMock(status_code=403, text="CF rotating IP mismatch")
                    return MagicMock(status_code=200, json=lambda: {"media_id_string": "777"})
                if cmd == "APPEND":
                    return MagicMock(status_code=204, text="")
                return MagicMock(status_code=200, json=lambda: {"media_id_string": "777"})

        @asynccontextmanager
        async def _up_pool(_t):
            yield _UpProxySess()

        fake_direct = MagicMock(
            post=AsyncMock(return_value=MagicMock(status_code=403, text="Direct blocked")),
            close=AsyncMock(),
        )
        with (
            patch("app.clients.SessionStore.get", return_value=MagicMock(lookup=_up_lk, invalidate=AsyncMock())),
            patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
            patch("app.clients.pooled_client", _up_pool),
            patch("app.clients._direct_session", return_value=fake_direct),
            patch("app.clients.warm_session", AsyncMock(side_effect=[("ct0_1", {}), ("ct0_1", {}), ("ct0_2", {})])),
        ):
            up_res = await media_upload(tok, b"PNGDATA", "image/png")
        assert up_res["status"] == "ok"
        assert proxy_init_calls == 2
    finally:
        reset_request_proxy(ctx_tok2)

    # 4. _action_via_browser_impl evicts ResponseCache on 401, and v2_tweets_search_recent skips Playwright on proxy warm-up failure & preserves 429
    rc = ResponseCache.get()
    await rc.store("UserByRestId", {"userId": "88"}, tok, {"status": "ok", "data": {"data": {"user": {"id": "88"}}}})
    act_page = MagicMock(
        goto=AsyncMock(return_value=MagicMock(status=200)),
        evaluate=AsyncMock(return_value={"status": 401, "body": {"errors": [{"code": 89}]}}),
        close=AsyncMock(),
    )
    act_ctx = MagicMock(new_page=AsyncMock(return_value=act_page), cookies=AsyncMock(return_value=[]))
    with (
        patch("playwright_search.ContextPool.get", return_value=MagicMock(acquire=AsyncMock(return_value=act_ctx), invalidate=AsyncMock(), release=AsyncMock())),
        patch("playwright_search.asyncio.sleep", AsyncMock()),
    ):
        act_res = await _action_via_browser_impl(tok, "https://x.com/i/api/1.1/blocks/destroy.json")
    assert act_res["status"] == "invalid"
    assert (await rc.lookup("UserByRestId", {"userId": "88"}, tok)) is None

    pw_spy = AsyncMock(return_value={"status": "error", "http_status": 502, "error": "timeout"})
    with (
        patch("app.routers.tweets.graphql_call", AsyncMock(return_value={"status": "error", "http_status": 502, "error": "warm-up failed: proxy dead"})),
        patch("app.routers.tweets.search_via_browser", pw_spy),
    ):
        resp_dead = await v2_tweets_search_recent(query="test", max_results=10, next_token=None, type="Latest", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert resp_dead.status_code == 502
    assert pw_spy.await_count == 0

    with (
        patch("app.routers.tweets.graphql_call", AsyncMock(return_value={"status": "error", "http_status": 429, "error": "rate limit"})),
        patch("app.routers.tweets.search_via_browser", pw_spy),
    ):
        resp_429 = await v2_tweets_search_recent(query="test", max_results=10, next_token=None, type="Latest", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert resp_429.status_code == 429


# ── 38. Pass 33: DM multi-call dead-proxy short-circuit & error surfacing (no fake 200 empty), plus XChat post-redirect goto>=400 guard ──

@pytest.mark.asyncio
async def test_pass33_dm_dead_proxy_short_circuit_no_fake_200_and_xchat_redirect_407():
    from app.routers.dm import v2_chat_conversations, v2_dm_conv_events, v2_dm_events
    from app.xchat_e2ee import send_xchat_dm_via_browser

    tok = "f" * 40

    # 1. Dead proxy (`warm-up failed:`) on DM endpoints short-circuits redundant GraphQL/REST calls
    #    AND surfaces 502/429/401 instead of returning fake HTTP 200 {"data": []}!
    gql_mock = AsyncMock(return_value={"status": "error", "http_status": 502, "error": "warm-up failed: proxy unreachable"})
    dm_mock = AsyncMock(return_value={"status": "error", "http_status": 502, "error": "should not be called"})
    with (
        patch("app.routers.dm.graphql_call", gql_mock),
        patch("app.routers.dm.dm_call", dm_mock),
    ):
        r_convs = await v2_chat_conversations(
            pagination_token=None, max_results=10, mode="auto",
            dm_pin=None, x_dm_pin=None, authorization=f"Bearer {tok}", auth_token=None, raw=0,
        )
        r_conv_ev = await v2_dm_conv_events(
            conversation_id="111-222", max_results=10, pagination_token=None, event_types=None,
            dm_event_fields=None, expansions=None, media_fields=None, user_fields=None,
            tweet_fields=None, mode="auto", dm_pin=None, x_dm_pin=None,
            authorization=f"Bearer {tok}", auth_token=None, raw=0,
        )
        r_events = await v2_dm_events(
            max_results=10, pagination_token=None, event_types=None, dm_event_fields=None,
            expansions=None, media_fields=None, user_fields=None, tweet_fields=None,
            include_requests=1, mode="auto", authorization=f"Bearer {tok}", auth_token=None, raw=0,
        )
    assert r_convs.status_code == 502
    assert r_conv_ev.status_code == 502
    assert r_events.status_code == 502
    assert gql_mock.await_count == 3  # Exactly 1 call per endpoint, NOT 2!
    assert dm_mock.await_count == 0   # Short-circuited REST fallback completely!

    # 2. XChat post-PIN redirect `page.goto` returning HTTP 407 immediately evicts XChatContextPool & returns 502
    nav_calls = 0

    class _RedirPage:
        url = "https://x.com/i/chat"
        async def goto(self, target_url, **kw):
            nonlocal nav_calls
            nav_calls += 1
            return MagicMock(status=200 if nav_calls == 1 else 407)
        async def close(self):
            pass

    x_ctx = MagicMock(new_page=AsyncMock(return_value=_RedirPage()))
    x_inv = AsyncMock()
    with (
        patch("app.xchat_e2ee.PlaywrightPool.get", return_value=MagicMock(semaphore=asyncio.Semaphore(1))),
        patch("app.xchat_e2ee.XChatContextPool.get", return_value=MagicMock(acquire=AsyncMock(return_value=x_ctx), invalidate=x_inv, release=AsyncMock())),
        patch("app.xchat_e2ee._ensure_pin_unlocked", AsyncMock(return_value=True)),
    ):
        send_redir = await send_xchat_dm_via_browser(tok, "1234", "111-222", "hello")
    assert send_redir["status"] == "error"
    assert send_redir["http_status"] == 502
    x_inv.assert_awaited_once_with(tok)


# ── 39. Pass 35: Redaction after `: `/`.`/`?`, numeric-password schemeless-@ normalization, proxy error-body redaction, & router Playwright fallback guards ──

@pytest.mark.asyncio
async def test_pass35_redaction_punctuation_numeric_pass_norm_and_router_playwright_guards(monkeypatch):
    from contextlib import asynccontextmanager
    from app.clients import _graphql_call_once
    from app.config import normalize_proxy_input, redact_proxy_creds, validate_proxy_url
    from app.routers.dm import DMSendBody, v2_dm_send
    from app.routers.users import v2_mentions, v2_user_by_id, v2_user_followers, v2_user_tweets_replies
    from playwright_search import fetch_via_browser

    tok = "e" * 40

    # 1. redact_proxy_creds masks credentials followed by `: reason`, `.`, `?`, `#`, single-label host, & trailing dot
    assert redact_proxy_creds("Proxy http://usr:secret1@31.6.46.27:12323: connection refused.") == (
        "Proxy http://***@31.6.46.27:12323: connection refused."
    )
    assert redact_proxy_creds("Failed http://usr:secret2@31.6.46.27:12323.") == (
        "Failed http://***@31.6.46.27:12323."
    )
    assert redact_proxy_creds("Bad http://usr:secret3@31.6.46.27:12323?foo=1#bar") == (
        "Failed".replace("Failed", "Bad") + " http://***@31.6.46.27:12323?foo=1#bar"
    )
    assert redact_proxy_creds("err usr:secret4@squid:3128 and proxy.example.com.:8080:usr:secret5") == (
        "err ***@squid:3128 and proxy.example.com.:8080:***"
    )
    # Must NOT falsely redact port+query URLs with @handle
    assert redact_proxy_creds("http://example.com:8080?q=@alice") == "http://example.com:8080?q=@alice"

    # 2. normalize_proxy_input handles `user:12345:secret@host:port`, trailing `/` on schemeless, & nested quotes
    assert validate_proxy_url(normalize_proxy_input("admin:12345:secret@31.6.46.27:12323")) == (
        "http://admin:12345%3Asecret@31.6.46.27:12323"
    )
    assert normalize_proxy_input("31.6.46.27:12323/") == "http://31.6.46.27:12323"
    assert normalize_proxy_input("[2606:4700::1]:8080/") == "http://[2606:4700::1]:8080"
    assert normalize_proxy_input("'\"http://31.6.46.27:12323\"'") == "http://31.6.46.27:12323"

    # 3. Proxy 407 HTML body echoing proxy credentials in _graphql_call_once is redacted
    class _Proxy407Sess:
        async def get(self, *a, **kw):
            return MagicMock(status_code=407, text="<html>Cache Access Denied via http://usr:leakpass@31.6.46.27:12323: denied</html>")

    @asynccontextmanager
    async def _p407_pool(_t):
        yield _Proxy407Sess()

    with (
        patch("app.clients.pooled_client", _p407_pool),
        patch("app.clients.warm_session", AsyncMock(return_value=("ct0_x", {}))),
        patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
    ):
        gql_407 = await _graphql_call_once("UserByRestId", {"userId": "1"}, tok)
    assert gql_407["http_status"] == 502
    assert "leakpass" not in gql_407["error"]
    assert "***@31.6.46.27:12323" in gql_407["error"]

    # 4. fetch_via_browser gracefully returns 502 (with redacted error) when ContextPool.acquire raises
    with patch(
        "playwright_search.ContextPool.get",
        return_value=MagicMock(acquire=AsyncMock(side_effect=RuntimeError("Playwright disabled via http://usr:pwsecret@31.6.46.27:12323"))),
    ):
        pw_unavail = await fetch_via_browser(tok, "https://x.com/i/user/1", "/UserByRestId")
    assert pw_unavail["status"] == "error"
    assert pw_unavail["http_status"] == 502
    assert "pwsecret" not in pw_unavail["error"]

    # 5. Router Playwright fallbacks: skip on `warm-up failed:`, preserve 429, no false 404/400 on proxy/auth failure
    monkeypatch.setenv("PLAYWRIGHT_FALLBACK", "1")
    pw_spy = AsyncMock(return_value={"status": "error", "http_status": 502, "error": "browser timeout"})
    with (
        patch("app.routers.users.graphql_call", AsyncMock(return_value={"status": "error", "http_status": 502, "error": "warm-up failed: proxy 407"})),
        patch("app.routers.users._cached_profile", return_value=None),
        patch("app.routers.users.fetch_via_browser", pw_spy),
    ):
        r_u = await v2_user_by_id("123", authorization=f"Bearer {tok}", auth_token=None, raw=0)
        r_f = await v2_user_followers("123", max_results=10, pagination_token=None, authorization=f"Bearer {tok}", auth_token=None, raw=0)
        r_r = await v2_user_tweets_replies("123", max_results=10, pagination_token=None, authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_u.status_code == 502
    assert r_f.status_code == 502
    assert r_r.status_code == 502
    assert pw_spy.await_count == 0

    # Non-JSON / http_status=200 upstream error on Followers must return 502, NOT false 404!
    with (
        patch("app.routers.users.graphql_call", AsyncMock(return_value={"status": "error", "http_status": 200, "error": "non-JSON response"})),
        patch("app.routers.users.resolve_screen_name", AsyncMock(return_value=None)),
    ):
        r_f_nonjson = await v2_user_followers("123", max_results=10, pagination_token=None, authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_f_nonjson.status_code == 502

    # v2_mentions propagates 502 / 401 when resolve_screen_name fails due to proxy / auth instead of false 400!
    with patch(
        "app.playwright_helpers.fetch_via_browser",
        AsyncMock(return_value={"status": "error", "http_status": 502, "error": "browser navigation HTTP 407"}),
    ):
        r_m_502 = await v2_mentions("123", max_results=10, pagination_token=None, username=None, authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_m_502.status_code == 502

    with patch(
        "app.playwright_helpers.fetch_via_browser",
        AsyncMock(return_value={"status": "invalid", "http_status": 401, "error": "browser navigation HTTP 401"}),
    ):
        r_m_401 = await v2_mentions("123", max_results=10, pagination_token=None, username=None, authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_m_401.status_code == 401

    # v2_dm_send with X-DM-Pin skips browser launch when dm_call failed with dead-proxy 502 warmup
    e2ee_spy = AsyncMock()
    with (
        patch("app.routers.dm.resolve_me_id", AsyncMock(return_value="111")),
        patch("app.routers.dm.dm_call", AsyncMock(return_value={"status": "error", "http_status": 502, "error": "warm-up failed: proxy dead"})),
        patch("app.routers.dm.send_xchat_dm_via_browser", e2ee_spy),
    ):
        r_dm_dead = await v2_dm_send(participant_id="222", body=DMSendBody(text="hi"), dm_pin=None, x_dm_pin="1234", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_dm_dead.status_code == 502
    assert e2ee_spy.await_count == 0


# ── 40. Pass 37: Captive-portal 200 warm_session guard, TIDProvider _fetch_home_via_client direct fallback, & v2_chat_messages proxy/auth propagation ──

@pytest.mark.asyncio
async def test_pass37_captive_portal_warm_tid_client_direct_fallback_and_chat_messages(monkeypatch):
    from contextlib import asynccontextmanager
    from app.auth import WarmNetworkError, warm_session
    from app.config import reset_request_proxy, set_request_proxy
    from app.routers.dm import DMSendBody, v2_chat_messages
    from tid_provider import TIDProvider

    tok = "a" * 40

    # 1. Proxy captive-portal 200 OK HTML (no twid, no X markers) raises WarmNetworkError(502), NOT InvalidTokenError(401)!
    captive_client = MagicMock()
    captive_client.cookies = MagicMock()
    captive_client.cookies.jar = MagicMock(__iter__=lambda self: iter([]), clear=MagicMock())
    captive_client.get = AsyncMock(return_value=MagicMock(status_code=200, text="<html><body>Proxy Subscription Expired</body></html>"))
    cp_inv = AsyncMock()
    px_tok = set_request_proxy("http://31.6.46.27:12323")
    try:
        with (
            patch("app.auth.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None))),
            patch("app.auth.ClientPool.get", return_value=MagicMock(invalidate=cp_inv)),
        ):
            with pytest.raises(WarmNetworkError) as exc_cap:
                await warm_session(captive_client, tok)
        assert exc_cap.value.http_status == 502
        cp_inv.assert_awaited_once_with(tok, all_proxies=False)

        # 2. TIDProvider._fetch_home_via_client falls back to direct when proxy fails (preserving logged-in loading-x-anim SVG!)
        import playwright_search as _pws
        monkeypatch.setattr(_pws, "PLAYWRIGHT_ENABLED", False)
        seen_cffi_proxies = []

        class _FakeCffiSess:
            def __init__(self, **kw):
                self._px = kw.get("proxies")
                seen_cffi_proxies.append(self._px)
            async def get(self, url):
                if self._px:
                    return MagicMock(status_code=407, text="Proxy Auth Required")
                return MagicMock(status_code=200, text="<html><svg id='loading-x-anim-0'></svg><script src='https://abs.twimg.com/responsive-web/client-web/ondemand.s.1234abcda.js'></script></html>")
            async def close(self):
                pass

        tp = TIDProvider()
        with (
            patch("curl_cffi.requests.AsyncSession", side_effect=lambda **kw: _FakeCffiSess(**kw)),
            patch("tid_provider.ClientTransaction", return_value="CT_DIRECT_FALLBACK"),
            patch("tid_provider._BoundedSession") as mock_bs,
        ):
            bs_inst = MagicMock()
            bs_inst.__enter__.return_value = bs_inst
            bs_inst.proxies = {}
            bs_inst.get.return_value = MagicMock(
                status_code=200,
                text="https://abs.twimg.com/responsive-web/client-web/ondemand.s.1234abcda.js",
                content=b"(self.webpackChunk=1)",
            )
            mock_bs.return_value = bs_inst
            await tp._refresh(tok)
        assert tp._ct == "CT_DIRECT_FALLBACK"
        assert len(seen_cffi_proxies) == 2
        assert seen_cffi_proxies[0] == {"http": "http://31.6.46.27:12323", "https": "http://31.6.46.27:12323"}
        assert seen_cffi_proxies[1] is None
    finally:
        reset_request_proxy(px_tok)

    # 3. v2_chat_messages propagates 502/401 on proxy/auth error instead of false 501 Not Implemented
    @asynccontextmanager
    async def _warm_err_pool(_t):
        yield MagicMock()

    with (
        patch("app.auth.pooled_client", _warm_err_pool),
        patch("app.auth.warm_session", AsyncMock(side_effect=WarmNetworkError("proxy dead", http_status=502))),
    ):
        r_cm_502 = await v2_chat_messages(
            conversation_id="111-222", body=DMSendBody(text="hi"),
            dm_pin=None, x_dm_pin=None, authorization=f"Bearer {tok}", auth_token=None, raw=0,
        )
    assert r_cm_502.status_code == 502

    # 5) _rest_call_once & _dm_call_once: HTTP 200 HTML captive portal -> 502 error + pool eviction,
    #    while empty 204 No Content stays status="ok"; /2/trends preserves 429; _JSONFormatter redacts nested/exc extras.
    import json as _json_mod
    import logging as _logging_mod
    from app.clients import _dm_call_once, _rest_call_once
    from app.observability import _JSONFormatter
    from app.routers.trends import v2_trends

    class _FakeResp:
        def __init__(self, status_code: int, text: str):
            self.status_code = status_code
            self.text = text

        def json(self):
            return _json_mod.loads(self.text)

    fake_sess = MagicMock()
    fake_sess.request = AsyncMock(return_value=_FakeResp(200, "<!DOCTYPE html><html><body>Proxy Captive Portal http://u:secret99@31.6.46.27:12323</body></html>"))

    @asynccontextmanager
    async def _fake_pool(_t):
        yield fake_sess

    inv_mock = AsyncMock()
    with (
        patch("app.clients.pooled_client", _fake_pool),
        patch("app.clients.warm_session", AsyncMock(return_value=("ct0_ok", {"twid": "u%3D1"}))),
        patch("app.clients.ClientPool.invalidate", inv_mock),
    ):
        r_html_rest = await _rest_call_once("trends/place.json?id=1", tok, method="GET")
        r_html_dm = await _dm_call_once("dm/user_updates.json", tok, method="GET")
        fake_sess.request = AsyncMock(return_value=_FakeResp(204, ""))
        r_empty_204 = await _rest_call_once("media/metadata/create.json", tok, method="POST", json_body={"media_id": "1"})

    assert r_html_rest["status"] == "error" and r_html_rest["http_status"] == 502
    assert "secret99" not in r_html_rest.get("raw", "")
    assert r_html_dm["status"] == "error" and r_html_dm["http_status"] == 502
    assert "secret99" not in r_html_dm.get("raw", "")
    assert inv_mock.await_count == 2
    assert r_empty_204["status"] == "ok" and r_empty_204["data"] == {}

    with patch("app.routers.trends.rest_call", AsyncMock(return_value={"status": "error", "http_status": 429, "error": "Rate limit exceeded"})):
        r_trends_429 = await v2_trends(woeid=1, authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_trends_429.status_code == 429

    jfmt = _JSONFormatter()
    rec = _logging_mod.LogRecord("xapi.test", _logging_mod.WARNING, __file__, 1, "check", (), None)
    rec.nested = {"err": RuntimeError("tunnel failed http://usr:logsecret88@31.6.46.27:12323")}
    formatted_log = jfmt.format(rec)
    assert "logsecret88" not in formatted_log
    assert "***@31.6.46.27:12323" in formatted_log

    # 6) Pass 40: v2_dm_media_proxy rejects HTTP 200 HTML captive portal & retries cleanly;
    #    v2_dm_send_to_conv skips XChat browser launch on dead-proxy 502;
    #    XChatContextPool._drain_close holds _closing_count across CancelledError;
    #    _action_via_browser_impl redacts creds & rejects 200 HTML captive portal.
    from app.routers.dm import v2_dm_media_proxy, v2_dm_send_to_conv
    from playwright_search import XChatContextPool, _action_via_browser_impl

    ton_media_calls = 0

    class _TonCaptiveSess:
        def __init__(self):
            self.cookies = MagicMock()

        async def get(self, url, headers=None):
            nonlocal ton_media_calls
            ton_media_calls += 1
            if ton_media_calls == 1:
                return MagicMock(
                    status_code=200,
                    content=b"<!DOCTYPE html><html><body>Captive Portal</body></html>",
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            return MagicMock(status_code=200, content=b"\xff\xd8\xff\xe0REALJPEG", headers={"content-type": "image/jpeg"})

    @asynccontextmanager
    async def _ton_captive_pool(_t):
        yield _TonCaptiveSess()

    with (
        patch("app.client_pool.pooled_client", _ton_captive_pool),
        patch("app.routers.dm.warm_session", AsyncMock(return_value=("ct0_m", {"twid": "u%3D1"}))),
    ):
        r_media_ok = await v2_dm_media_proxy(
            dm_id="111", media_id="222", resource_id="img.jpg",
            authorization=f"Bearer {tok}", auth_token=None,
        )
    assert r_media_ok.status_code == 200
    assert r_media_ok.body == b"\xff\xd8\xff\xe0REALJPEG"
    assert ton_media_calls == 2

    pw_send_spy = AsyncMock()
    with (
        patch("app.auth.pooled_client", _warm_err_pool),
        patch("app.auth.warm_session", AsyncMock(side_effect=WarmNetworkError("proxy dead", http_status=502))),
        patch("app.routers.dm.send_xchat_dm_via_browser", pw_send_spy),
    ):
        r_conv_502 = await v2_dm_send_to_conv(
            conversation_id="111-222", body=DMSendBody(text="hi"), dm_pin=None,
            x_dm_pin="1234", authorization=f"Bearer {tok}", auth_token=None, raw=0,
        )
    assert r_conv_502.status_code == 502
    assert pw_send_spy.await_count == 0

    # XChatContextPool._drain_close keeps _closing_count > 0 even if acquire() is cancelled mid-close
    xpool_c = XChatContextPool()
    close_gate = asyncio.Event()
    close_started = asyncio.Event()

    async def _gated_close():
        close_started.set()
        await close_gate.wait()

    import hashlib as _hl40
    xkey = _hl40.sha256(f"xchat:{tok}".encode()).hexdigest()[:16]
    old_xctx = MagicMock(pages=[], close=AsyncMock(side_effect=_gated_close))
    new_xctx = MagicMock(pages=[], add_init_script=AsyncMock(), add_cookies=AsyncMock(), close=AsyncMock())
    xpool_c._ctxs[xkey] = old_xctx
    xpool_c._ctx_proxy[xkey] = "http://old.proxy.example:8080"
    xpool_c._ctx_use[id(old_xctx)] = 0

    fake_drv = MagicMock()
    fake_drv.chromium.launch_persistent_context = AsyncMock(return_value=new_xctx)
    with (
        patch("app.config.proxy_for_token", return_value="http://new.proxy.example:8080"),
        patch("app.config.playwright_proxy_for_token", return_value={"server": "http://new.proxy.example:8080"}),
        patch("playwright_search.PlaywrightPool.get", return_value=MagicMock(driver=AsyncMock(return_value=fake_drv))),
        patch("playwright_search._apply_session_cookies", AsyncMock()),
    ):
        acq_task1 = asyncio.create_task(xpool_c.acquire(tok))
        await close_started.wait()
        assert xpool_c._closing_count.get(xkey) == 1
        acq_task1.cancel()
        with pytest.raises(asyncio.CancelledError):
            await acq_task1
        # Still closing in background -> _closing_count must STILL be 1!
        assert xpool_c._closing_count.get(xkey) == 1
        acq_task2 = asyncio.create_task(xpool_c.acquire(tok))
        await asyncio.sleep(0.02)
        assert fake_drv.chromium.launch_persistent_context.await_count == 0
        close_gate.set()
        got_xctx = await acq_task2
        assert got_xctx is new_xctx
        assert xpool_c._closing_count.get(xkey, 0) == 0

    # _action_via_browser_impl redacts creds & rejects 200 HTML captive portal
    fake_page = MagicMock()
    fake_page.goto = AsyncMock(return_value=MagicMock(status=200))
    fake_page.evaluate = AsyncMock(return_value={
        "status": 200,
        "body": "<html><body>Proxy error http://usr:actsecret@31.6.46.27:12323</body></html>",
    })
    fake_page.close = AsyncMock()
    fake_bctx = MagicMock(new_page=AsyncMock(return_value=fake_page), cookies=AsyncMock(return_value=[]))
    cp_inv_spy = AsyncMock()
    with (
        patch("playwright_search.ContextPool.get", return_value=MagicMock(acquire=AsyncMock(return_value=fake_bctx), release=AsyncMock(), invalidate=cp_inv_spy)),
        patch("playwright_search.asyncio.sleep", AsyncMock()),
    ):
        r_act_html = await _action_via_browser_impl(tok, "https://x.com/i/api/1.1/blocks/destroy.json")
    assert r_act_html["status"] == "error" and r_act_html["http_status"] == 502
    assert "actsecret" not in r_act_html.get("raw", "")
    assert cp_inv_spy.await_count == 1

    # 7) Pass 41: _is_fatal_proxy_or_auth_err stops cascading DM calls on post-warmup `upstream request failed:`,
    #    and v2_chat_conversations skips launching XChat browser when proxy tunnel is dead (502).
    from app.routers.dm import v2_chat_conversations
    dm_spy_41 = AsyncMock()
    inbox_pw_spy = AsyncMock()
    with (
        patch("app.routers.dm.graphql_call", AsyncMock(return_value={
            "status": "error",
            "http_status": 502,
            "error": "upstream request failed: ProxyError: tunnel refused",
            "data": None,
        })),
        patch("app.routers.dm.dm_call", dm_spy_41),
        patch("app.routers.dm.unlock_and_read_xchat_inbox", inbox_pw_spy),
    ):
        r_convs_502 = await v2_chat_conversations(
            max_results=20, pagination_token=None, mode="auto",
            dm_pin=None, x_dm_pin="1234", authorization=f"Bearer {tok}", auth_token=None, raw=0,
        )
    assert r_convs_502.status_code == 502
    assert dm_spy_41.await_count == 0
    assert inbox_pw_spy.await_count == 0

    # 8) Pass 42: off-domain captive-portal HTTP 200 redirect on page.goto evicts ContextPool & XChatContextPool immediately,
    #    and redact_proxy_creds covers socks/socks4/socks4a without swallowing comma-separated URL lists.
    from app.config import redact_proxy_creds
    from app.xchat_e2ee import _handle_xchat_nav_status
    from playwright_search import _check_nav_response_error

    assert redact_proxy_creds("http://example.com,http://usr:sec42@31.6.46.27:12323") == "http://example.com,http://***@31.6.46.27:12323"
    assert redact_proxy_creds("socks4://usr:sec42b@31.6.46.27:1080") == "socks4://***@31.6.46.27:1080"
    assert redact_proxy_creds("PROXY_LIST=usr:sec42c@31.6.46.27:12323,u2:sec42d@1.2.3.4:8080") == "PROXY_LIST=***@31.6.46.27:12323,***@1.2.3.4:8080"

    cp_inv_42 = AsyncMock()
    xc_inv_42 = AsyncMock()
    captive_page = MagicMock(url="http://captive.isp.example/login?redir=x.com")
    with (
        patch("playwright_search.ContextPool.get", return_value=MagicMock(invalidate=cp_inv_42)),
        patch("app.xchat_e2ee.XChatContextPool.get", return_value=MagicMock(invalidate=xc_inv_42)),
    ):
        nav_err_42 = await _check_nav_response_error(tok, MagicMock(status=200), page=captive_page)
        xc_st_42 = await _handle_xchat_nav_status(tok, MagicMock(status=200), page=captive_page)
    assert nav_err_42 is not None and nav_err_42["http_status"] == 502
    assert xc_st_42 == 502
    cp_inv_42.assert_awaited_once_with(tok, all_proxies=False)
    xc_inv_42.assert_awaited_once_with(tok)

    # 9) Pass 43: SSRF local/wildcard-DNS hostnames (ip6-localhost, ip6-loopback, host.docker.internal,
    #    *.nip.io, *.sslip.io, localtest.me, *.internal, local hostname) blocked while http://squid:3128 preserved;
    #    and LogRecordFactory redacts child loggers & non-propagating loggers (e.g. uvicorn.error) + tracebacks.
    import io
    import logging as _logging
    import socket as _socket
    from app.config import validate_proxy_url
    from app.observability import install_proxy_log_record_factory

    assert validate_proxy_url("http://squid:3128") == "http://squid:3128"
    local_hn_43 = (_socket.gethostname() or "").strip().lower().rstrip(".")
    bad_hosts_43 = [
        "http://ip6-localhost:8080",
        "http://ip6-loopback:8080",
        "http://host.docker.internal:8080",
        "http://127.0.0.1.nip.io:8080",
        "http://127-0-0-1.sslip.io:8080",
        "http://sub.localtest.me:8080",
        "http://svc.internal:8080",
        "http://mybox.local:8080",
    ]
    if local_hn_43 and local_hn_43 != "squid":
        bad_hosts_43.append(f"http://{local_hn_43}:8000")
    for bh in bad_hosts_43:
        with pytest.raises(ValueError):
            validate_proxy_url(bh)

    install_proxy_log_record_factory()
    buf_43 = io.StringIO()
    nonprop_log = _logging.getLogger("uvicorn.error.test_pass43")
    nonprop_log.propagate = False
    nonprop_log.setLevel(_logging.INFO)
    h_43 = _logging.StreamHandler(buf_43)
    h_43.setFormatter(_logging.Formatter("%(message)s"))
    nonprop_log.addHandler(h_43)
    try:
        try:
            raise RuntimeError("tunnel failed http://usr:uvsecret43@31.6.46.27:12323")
        except RuntimeError:
            nonprop_log.exception("worker err %s", "31.6.46.27:12323:usr:uvshort43")
    finally:
        nonprop_log.removeHandler(h_43)
    rendered_43 = buf_43.getvalue()
    assert "uvsecret43" not in rendered_43
    assert "uvshort43" not in rendered_43
    assert "***@31.6.46.27:12323" in rendered_43
    assert "31.6.46.27:12323:***" in rendered_43
    assert redact_proxy_creds("err via http://u:p,a:s@31.6.46.27:12323/: refused") == "err via http://***@31.6.46.27:12323/: refused"
    assert redact_proxy_creds("PROXY_LIST=31.6.46.27:12323:u1:sec1,u2:sec2@1.2.3.4:8080") == "PROXY_LIST=31.6.46.27:12323:***,***@1.2.3.4:8080"

    # 10) Pass 44: login_with_auth_token rejects HTTP 200 captive-portal HTML without poisoning viewer cache,
    #     post-warmup dead-proxy (`upstream request failed:` / 407 `rejected by proxy/upstream`) skips Chromium
    #     in v2_tweets_search / v2_dm_send / v2_chat_messages, and XChatContextPool evicts on ERR_CONNECTION_RESET.
    from app.auth import login_with_auth_token
    from app.routers.dm import DMSendBody, v2_dm_send
    from app.routers.tweets import v2_tweets_search_recent
    from app.xchat_e2ee import _is_xchat_proxy_nav_exc

    assert _is_xchat_proxy_nav_exc("Page.goto: net::ERR_CONNECTION_RESET at https://x.com/i/chat", tok) is True

    pw_search_spy_44 = AsyncMock()
    with (
        patch("app.routers.tweets.graphql_call", AsyncMock(return_value={
            "status": "error",
            "http_status": 502,
            "error": "upstream request failed: ProxyError: tunnel dead",
            "data": None,
        })),
        patch("app.routers.tweets.search_via_browser", pw_search_spy_44),
    ):
        r_srch_44 = await v2_tweets_search_recent(query="tes", max_results=10, next_token=None, type="Latest", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_srch_44.status_code == 502
    assert pw_search_spy_44.await_count == 0

    pw_dm_spy_44 = AsyncMock()
    with (
        patch("app.routers.dm._resolve_me_or_error", AsyncMock(return_value=("999", None))),
        patch("app.routers.dm.dm_call", AsyncMock(return_value={
            "status": "error",
            "http_status": 502,
            "error": "rejected by proxy/upstream (HTTP 407)",
            "data": None,
        })),
        patch("app.routers.dm.send_xchat_dm_via_browser", pw_dm_spy_44),
    ):
        r_dms_44 = await v2_dm_send(participant_id="111", body=DMSendBody(text="hi"), dm_pin=None, x_dm_pin="1234", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_dms_44.status_code == 502
    assert pw_dm_spy_44.await_count == 0

    store_44 = MagicMock(
        lookup_viewer=AsyncMock(return_value=None),
        lookup=AsyncMock(return_value=None),
        invalidate=AsyncMock(),
        store_viewer=AsyncMock(),
    )
    cp_44 = MagicMock(invalidate=AsyncMock())
    html_v_resp = MagicMock(status_code=200, text="<html><body>Captive Portal</body></html>")
    mock_v_client = MagicMock(get=AsyncMock(return_value=html_v_resp))
    mock_v_client.cookies.jar = []

    @asynccontextmanager
    async def _v_pool_44(_t):
        yield mock_v_client

    with (
        patch("app.auth.SessionStore.get", return_value=store_44),
        patch("app.auth.ClientPool.get", return_value=cp_44),
        patch("app.auth.pooled_client", _v_pool_44),
        patch("app.auth.warm_session", AsyncMock(return_value=("ct0_44", {}))),
    ):
        login_44 = await login_with_auth_token(tok)
    assert login_44["status"] == "error" and login_44["http_status"] == 502
    store_44.store_viewer.assert_not_awaited()
    cp_44.invalidate.assert_awaited_once_with(tok, all_proxies=False)
    rec_clean_44 = _logging.getLogger("xapi.clean44").makeRecord(
        "xapi.clean44", _logging.INFO, "f.py", 1, "check %s", ("http://u:sec44@31.6.46.27:8080",), None
    )
    json_clean_44 = jfmt.format(rec_clean_44)
    assert "getMessage" not in json_clean_44 and "sec44" not in json_clean_44


@pytest.mark.asyncio
async def test_pass45_ssrf_cloud_imds_private_proxy_comma_password_and_router_fallbacks(monkeypatch):
    """Pass 45: block Cloud IMDS (Alibaba 100.100.100.200, Oracle 192.0.0.192, AWS IPv6 fd00:ec2::254)
    & private/CGNAT/ULA IPs unless ALLOW_PRIVATE_PROXY_IPS=1; reject broken userinfo colons (`usr:@` / `:pass@`);
    preserve commas inside proxy passwords via `split_proxy_list`; and prevent dead-proxy fallbacks on
    bookmarks/unblock/dm_block/dm_accept."""
    import app.config as cfg
    from app.config import normalize_proxy_input, split_proxy_list, validate_proxy_url
    from app.routers.bookmarks import BookmarkBody, v2_bookmark, v2_unbookmark
    from app.routers.dm import _accept_dm_conversation, v2_dm_block
    from app.routers.users import v2_unblock

    # 1. Cloud IMDS & non-global/private SSRF blocked by default
    for ssrf_px in (
        "http://100.100.100.200:80",          # Alibaba Cloud IMDS (CGNAT 100.64/10)
        "http://192.0.0.192:80",              # Oracle Cloud IMDS (is_global=True in Python 3.9!)
        "http://[fd00:ec2::254]:80",          # AWS EC2 IPv6 IMDSv2
        "http://192.168.10.19:8001",          # LAN / local service SSRF
        "http://172.17.0.1:2375",             # Docker bridge SSRF
        "http://10.0.0.1:8080",               # RFC 1918
        "http://100.64.1.2:8080",             # CGNAT
        "http://198.18.0.1:8080",             # RFC 2544
        "http://198.51.100.10:8080",          # TEST-NET-2
        "http://[2001:db8::1]:8080",          # RFC 3849
        "http://[::ffff:192.168.10.19]:8001", # IPv4-mapped private IP
        "http://[2002:c0a8:0a13::1]:8001",    # 6to4-wrapped private IP
    ):
        with pytest.raises(ValueError):
            validate_proxy_url(ssrf_px)

    # IPv4-mapped public IP remains valid (and canonicalizes RFC 5952 hex); ALLOW_PRIVATE_PROXY_IPS=1 allows LAN Squid while still blocking IMDS!
    assert validate_proxy_url("http://[::ffff:31.6.46.27]:12323") == "http://[::ffff:1f06:2e1b]:12323"
    assert validate_proxy_url("http://[::ffff:1f06:2e1b]:12323") == "http://[::ffff:1f06:2e1b]:12323"
    monkeypatch.setattr(cfg, "ALLOW_PRIVATE_PROXY_IPS", True)
    assert validate_proxy_url("http://192.168.10.50:3128") == "http://192.168.10.50:3128"
    for always_bad in ("http://100.100.100.200:80", "http://192.0.0.192:80", "http://[fd00:ec2::254]:80", "http://127.0.0.1:3128"):
        with pytest.raises(ValueError):
            validate_proxy_url(always_bad)
    monkeypatch.setattr(cfg, "ALLOW_PRIVATE_PROXY_IPS", False)

    # 2. Broken half-empty userinfo rejected while single-token auth preserved
    assert validate_proxy_url("http://mytoken@31.6.46.27:12323") == "http://mytoken@31.6.46.27:12323"
    for broken_ui in ("http://usr:@31.6.46.27:12323", "http://:pass@31.6.46.27:12323", "http://:@31.6.46.27:12323"):
        with pytest.raises(ValueError):
            validate_proxy_url(broken_ui)

    # 3. Comma-in-password preserved across split_proxy_list + normalize + validate
    split_res = split_proxy_list("http://u:a,b,c@31.6.46.27:12323,31.6.46.27:12323:u2:pa,ss,u3:x,y@1.2.3.4:8080")
    assert split_res == [
        "http://u:a,b,c@31.6.46.27:12323",
        "31.6.46.27:12323:u2:pa,ss",
        "u3:x,y@1.2.3.4:8080",
    ]
    assert [validate_proxy_url(normalize_proxy_input(x)) for x in split_res] == [
        "http://u:a%2Cb%2Cc@31.6.46.27:12323",
        "http://u2:pa%2Css@31.6.46.27:12323",
        "http://u3:x%2Cy@1.2.3.4:8080",
    ]

    # 4. Dead-proxy 404 (e.g. Squid/Nginx proxy error page) does NOT cascade into browser/secondary calls
    tok = "a" * 40
    dead_404 = {"status": "error", "http_status": 404, "error": "upstream request failed: ProxyError", "data": None}
    pw_click_spy = AsyncMock()
    rest_spy = AsyncMock()
    dm_spy = AsyncMock(side_effect=[dead_404, {"status": "ok", "http_status": 200, "data": {}}])

    with (
        patch("app.routers.bookmarks.graphql_call", AsyncMock(return_value=dead_404)),
        patch("app.routers.bookmarks.click_action_via_browser", pw_click_spy),
    ):
        r_bm = await v2_bookmark(body=BookmarkBody(tweet_id="123"), user_id="1", authorization=f"Bearer {tok}", auth_token=None, raw=0)
        r_unbm = await v2_unbookmark(user_id="1", tweet_id="123", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_bm.status_code == 404 and r_unbm.status_code == 404
    assert pw_click_spy.await_count == 0

    with (
        patch("app.routers.users.rest_call", AsyncMock(return_value=dead_404)),
        patch("app.routers.users.click_action_via_browser", pw_click_spy),
    ):
        r_unblk = await v2_unblock(source_user_id="1", target_user_id="2", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_unblk.status_code == 404
    assert pw_click_spy.await_count == 0

    with (
        patch("app.routers.dm._resolve_me_or_error", AsyncMock(return_value=("1", None))),
        patch("app.routers.dm.dm_call", AsyncMock(return_value=dead_404)),
        patch("app.routers.dm.rest_call", rest_spy),
    ):
        r_dmblk = await v2_dm_block(user_id="2", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_dmblk.status_code == 404
    assert rest_spy.await_count == 0

    with patch("app.routers.dm.dm_call", dm_spy):
        r_acc = await _accept_dm_conversation("1-2", tok, 0)
    assert r_acc.status_code == 404
    assert dm_spy.await_count == 1


@pytest.mark.asyncio
async def test_pass46_captive_portal_echo_url_offdomain_nonjson_and_octet_dm_media():
    """Pass 46: captive portal echoing `https://x.com/home` or redirecting off-domain raises
    WarmNetworkError(502) instead of false 401 InvalidTokenError; `is_dead_proxy_error_result`
    recognizes `non-JSON` & 502 gateway HTML (blocking browser fallbacks); 200 non-JSON evicts
    `SessionStore`; and `v2_dm_media_proxy` rejects HTML disguised as `application/octet-stream`."""
    from contextlib import asynccontextmanager
    from app.auth import WarmNetworkError, warm_session
    from app.clients import _graphql_call_once, is_dead_proxy_error_result
    from app.config import reset_request_proxy, set_request_proxy
    from app.routers.dm import v2_dm_media_proxy
    from app.routers.tweets import v2_tweets_search_recent

    tok = "a" * 40
    px_tok = set_request_proxy("http://31.6.46.27:12323")
    try:
        # 1a. Captive portal echoing `<input name="orig_url" value="https://x.com/home">` -> 502 WarmNetworkError, NOT 401!
        cap_echo_client = MagicMock()
        cap_echo_client.cookies = MagicMock()
        cap_echo_client.cookies.jar = MagicMock(__iter__=lambda self: iter([]), clear=MagicMock())
        cap_echo_client.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            url="https://x.com/home",
            text='<html><body>Login to continue to <input value="https://x.com/home"></body></html>',
        ))
        with (
            patch("app.auth.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None))),
            patch("app.auth.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
        ):
            with pytest.raises(WarmNetworkError) as exc_echo:
                await warm_session(cap_echo_client, tok)
        assert exc_echo.value.http_status == 502

        # 1b. Off-domain captive portal redirect -> 502 WarmNetworkError
        cap_redir_client = MagicMock()
        cap_redir_client.cookies = MagicMock()
        cap_redir_client.cookies.jar = MagicMock(__iter__=lambda self: iter([]), clear=MagicMock())
        cap_redir_client.get = AsyncMock(return_value=MagicMock(
            status_code=200,
            url="http://portal.isp.example/login",
            text="<html><script src='https://abs.twimg.com/x.js'></script></html>",
        ))
        with (
            patch("app.auth.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None))),
            patch("app.auth.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
        ):
            with pytest.raises(WarmNetworkError) as exc_redir:
                await warm_session(cap_redir_client, tok)
        assert exc_redir.value.http_status == 502
    finally:
        reset_request_proxy(px_tok)

    # 2. is_dead_proxy_error_result recognizes non-JSON & 502 HTML gateway -> blocks Playwright search fallback
    non_json_err = {"status": "error", "http_status": 502, "error": "non-JSON response", "data": None}
    gw_502_err = {"status": "error", "http_status": 502, "error": "<html><title>502 Bad Gateway</title></html>", "data": None}
    assert is_dead_proxy_error_result(non_json_err) is True
    assert is_dead_proxy_error_result(gw_502_err) is True
    pw_search_spy = AsyncMock()
    with (
        patch("app.routers.tweets.graphql_call", AsyncMock(return_value=non_json_err)),
        patch("app.routers.tweets.search_via_browser", pw_search_spy),
    ):
        r_srch = await v2_tweets_search_recent(query="test", max_results=10, next_token=None, type="Latest", authorization=f"Bearer {tok}", auth_token=None, raw=0)
    assert r_srch.status_code == 502
    assert pw_search_spy.await_count == 0

    # 3. _graphql_call_once evicts BOTH SessionStore and ClientPool on 200 non-JSON
    ss_inv = AsyncMock()
    cp_inv = AsyncMock()
    fake_gql_client = MagicMock(get=AsyncMock(return_value=MagicMock(
        status_code=200,
        text="<html>Captive</html>",
        json=MagicMock(side_effect=json.JSONDecodeError("err", "<html>", 0)),
    )))

    @asynccontextmanager
    async def _fake_pool_46(_t):
        yield fake_gql_client

    with (
        patch("app.clients.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None), invalidate=ss_inv)),
        patch("app.clients.ClientPool.get", return_value=MagicMock(invalidate=cp_inv)),
        patch("app.clients.pooled_client", _fake_pool_46),
        patch("app.clients.warm_session", AsyncMock(return_value=("ct0_46", {}))),
        patch("app.clients.TIDProvider.get", return_value=MagicMock(generate=AsyncMock(return_value="tid"))),
    ):
        gql_46 = await _graphql_call_once("UserByRestId", {"userId": "1"}, tok)
    assert gql_46["http_status"] == 502
    ss_inv.assert_awaited_once_with(tok, all_proxies=False)
    cp_inv.assert_awaited_once_with(tok, all_proxies=False)

    # 4. v2_dm_media_proxy rejects HTML disguised as application/octet-stream
    octet_html_resp = MagicMock(
        status_code=200,
        headers={"content-type": "application/octet-stream"},
        content=b"<html><body>Captive Portal</body></html>",
    )
    dm_media_client = MagicMock(
        get=AsyncMock(return_value=octet_html_resp),
        cookies=MagicMock(set=MagicMock()),
    )

    @asynccontextmanager
    async def _dm_pool_46(_t):
        yield dm_media_client

    with (
        patch("app.routers.dm.SessionStore.get", return_value=MagicMock(lookup=AsyncMock(return_value=None), invalidate=AsyncMock())),
        patch("app.client_pool.ClientPool.get", return_value=MagicMock(invalidate=AsyncMock())),
        patch("app.client_pool.pooled_client", _dm_pool_46),
        patch("app.routers.dm.warm_session", AsyncMock(return_value=("ct0_46", {}))),
    ):
        r_dmm = await v2_dm_media_proxy(dm_id="111", media_id="222", resource_id="img.jpg", authorization=f"Bearer {tok}", auth_token=None)
    assert r_dmm.status_code == 502
