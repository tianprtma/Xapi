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
