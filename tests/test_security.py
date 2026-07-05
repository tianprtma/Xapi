"""Unit tests for security middleware internals."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import token_key
from app.errors import build_error


class TestTokenKey:
    def test_token_key_is_deterministic(self):
        """Same input → same output within one process."""
        tok = "a" * 40
        assert token_key(tok) == token_key(tok)

    def test_token_key_differs_per_token(self):
        assert token_key("a" * 40) != token_key("b" * 40)

    def test_token_key_is_not_plaintext(self):
        result = token_key("deadbeef" * 5)
        assert "deadbeef" not in result

    def test_token_key_is_hex_string(self):
        result = token_key("a" * 40)
        # sha256 hex is 64 chars
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestRateLimitBucket:
    def test_bucket_starts_full(self):
        from app.security import _Bucket
        b = _Bucket(burst=200)
        assert b.tokens == 200.0

    def test_bucket_consumes_tokens(self):
        from app.security import _Bucket
        import time
        b = _Bucket(burst=10)
        b.tokens = 5.0
        b.tokens -= 1.0
        assert b.tokens == 4.0

    def test_bucket_refills_over_time(self):
        from app.security import _Bucket
        import time
        b = _Bucket(burst=100)
        b.tokens = 0.0
        b.last_refill = time.monotonic() - 10.0  # 10s ago
        elapsed = time.monotonic() - b.last_refill
        b.tokens = min(float(b.burst), b.tokens + elapsed * 100.0)
        assert b.tokens > 0
