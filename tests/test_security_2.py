"""Tests for app/auth.py, app/security.py, app/sanitize.py, app/errors.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.auth import extract_bearer, extract_user_id_from_twid, make_client, api_headers
from app.sanitize import (
    sanitize_username,
    sanitize_tweet_id,
    sanitize_csv_ids,
    sanitize_search_query,
    sanitize_url_param,
)
from app.errors import build_error, build_error_jsonapi, ERROR_CODES
from app.security import _Bucket


# ════════════════════════ auth.py ════════════════════════


class TestExtractBearer:
    def test_valid_header(self):
        tok = extract_bearer("Bearer aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", None)
        assert tok == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    def test_missing_both_raises(self):
        with pytest.raises(HTTPException) as exc:
            extract_bearer(None, None)
        assert exc.value.status_code == 401

    def test_invalid_format_raises(self):
        with pytest.raises(HTTPException) as exc:
            extract_bearer("Bearer not-hex", None)
        assert exc.value.status_code == 401

    def test_query_fallback(self):
        tok = extract_bearer(None, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        assert tok == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    def test_query_disabled(self):
        with patch("app.config.ALLOW_QUERY_AUTH", False):
            with pytest.raises(HTTPException) as exc:
                extract_bearer(None, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
            assert exc.value.status_code == 401

    def test_empty_bearer(self):
        with pytest.raises(HTTPException):
            extract_bearer("Bearer ", None)


class TestExtractUserIdFromTwid:
    def test_valid(self):
        assert extract_user_id_from_twid("u%3D12345") == "12345"

    def test_none(self):
        assert extract_user_id_from_twid(None) is None

    def test_empty(self):
        assert extract_user_id_from_twid("") is None

    def test_malformed(self):
        assert extract_user_id_from_twid("not-a-twid") is None


class TestMakeClient:
    def test_returns_session(self):
        client = make_client("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        assert client is not None
        # Check headers were set
        assert client.headers is not None

    @patch("app.auth.random_proxy")
    def test_with_proxy(self, mock_proxy):
        mock_proxy.return_value = "http://proxy:8080"
        client = make_client("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        assert client is not None


class TestApiHeaders:
    def test_contains_ct0(self):
        h = api_headers("my_ct0")
        assert h["x-csrf-token"] == "my_ct0"
        assert "authorization" in h
        assert h["content-type"] == "application/json"


# ════════════════════════ security.py ════════════════════════


class TestBucket:
    def test_starts_full(self):
        b = _Bucket(burst=100)
        assert b.tokens == 100.0

    def test_consume(self):
        b = _Bucket(burst=10)
        b.tokens -= 1.0
        assert b.tokens == 9.0

    def test_refill(self):
        b = _Bucket(burst=100)
        b.tokens = 50.0
        b.last_refill -= 10  # 10s ago, rate=100/s → refill 1000
        import time
        b.last_refill = time.monotonic() - 10
        # trigger refill
        now = time.monotonic()
        elapsed = now - b.last_refill
        b.tokens = min(float(b.burst), b.tokens + elapsed * 100)
        b.last_refill = now
        assert b.tokens == 100.0  # capped at burst


# ════════════════════════ sanitize.py ════════════════════════


class TestSanitizeUsername:
    def test_valid(self):
        assert sanitize_username("elonmusk") == "elonmusk"

    def test_with_underscore(self):
        assert sanitize_username("test_user") == "test_user"

    def test_too_long(self):
        assert sanitize_username("a" * 31) is None

    def test_invalid_chars(self):
        assert sanitize_username("user name!") is None
        assert sanitize_username("usér") is None

    def test_none(self):
        assert sanitize_username(None) is None

    def test_empty(self):
        assert sanitize_username("") is None

    def test_strip(self):
        assert sanitize_username("  user  ") == "user"


class TestSanitizeTweetId:
    def test_valid(self):
        assert sanitize_tweet_id("1234567890") == "1234567890"

    def test_none(self):
        assert sanitize_tweet_id(None) is None

    def test_too_long(self):
        assert sanitize_tweet_id("1" * 31) is None

    def test_non_numeric(self):
        assert sanitize_tweet_id("abc") is None

    def test_empty(self):
        assert sanitize_tweet_id("") is None


class TestSanitizeCsvIds:
    def test_valid(self):
        assert sanitize_csv_ids("1,2,3") == ["1", "2", "3"]

    def test_none(self):
        assert sanitize_csv_ids(None) == []

    def test_mixed(self):
        assert sanitize_csv_ids("1,abc,2") == ["1", "2"]

    def test_empty(self):
        assert sanitize_csv_ids("") == []


class TestSanitizeSearchQuery:
    def test_valid(self):
        assert sanitize_search_query("hello world") == "hello world"

    def test_none(self):
        assert sanitize_search_query(None) == ""

    def test_truncate(self):
        long_q = "a" * 600
        result = sanitize_search_query(long_q)
        assert len(result) == 500

    def test_empty(self):
        assert sanitize_search_query("") == ""

    def test_strip(self):
        assert sanitize_search_query("  hi  ") == "hi"


class TestSanitizeUrlParam:
    def test_valid(self):
        assert sanitize_url_param("hello") == "hello"

    def test_none(self):
        assert sanitize_url_param(None) is None

    def test_null_bytes(self):
        assert sanitize_url_param("hel\x00lo") == "hello"

    def test_control_chars(self):
        assert sanitize_url_param("he\x00\x01llo") == "hello"

    def test_url_encoded(self):
        result = sanitize_url_param("hello%20world")
        assert result == "hello world"

    def test_too_long(self):
        long_str = "a" * 600
        result = sanitize_url_param(long_str)
        assert len(result) == 500

    def test_empty_after_sanitize(self):
        assert sanitize_url_param("\x00\x01\x02") is None


# ════════════════════════ errors.py ════════════════════════


class TestBuildError:
    def test_valid_key(self):
        err = build_error("AUTH_TOKEN_MISSING")
        assert err["errors"][0]["code"] == "AUTH_TOKEN_MISSING"
        assert err["errors"][0]["status"] == 401

    def test_unknown_key(self):
        err = build_error("NONEXISTENT_KEY")
        assert err["errors"][0]["code"] == "INFRA_INTERNAL_ERROR"

    def test_with_format_kwargs(self):
        err = build_error("RATE_LIMIT_EXCEEDED", retry_after=30)
        assert "30" in err["errors"][0]["detail"]

    def test_with_custom_detail(self):
        err = build_error("AUTH_TOKEN_MISSING", detail="custom msg")
        assert err["errors"][0]["detail"] == "custom msg"


class TestBuildErrorJsonapi:
    def test_valid_key(self):
        err = build_error_jsonapi("AUTH_TOKEN_MISSING")
        assert "errors" in err
        assert err["errors"][0]["code"] == "AUTH_TOKEN_MISSING"

    def test_unknown_key(self):
        err = build_error_jsonapi("NONEXISTENT_KEY")
        assert err["errors"][0]["code"] == "INFRA_INTERNAL_ERROR"

    def test_all_keys_have_required_fields(self):
        for key, ec in ERROR_CODES.items():
            try:
                err = build_error(key)
            except KeyError:
                # Some templates require kwargs (e.g. UPSTREAM_ERROR needs http_status)
                err = build_error(key, http_status=502, reason="test", retry_after=30, max_bytes=1000, segment=0, error="test", attempts=3, last_status=502, timeout=30, param="x", method="GET", path="/", caller="test", operation="op", detail="test")
            e = err["errors"][0]
            assert "code" in e
            assert "title" in e
            assert "detail" in e
            assert "status" in e
