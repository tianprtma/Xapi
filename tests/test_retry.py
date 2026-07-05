"""Tests for app/retry.py — with_retry backoff logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.retry import with_retry


class TestWithRetry:
    async def test_ok_first_try(self):
        fn = AsyncMock(return_value={"status": "ok", "http_status": 200})
        result = await with_retry(fn, max_attempts=3)
        assert result["status"] == "ok"
        fn.assert_called_once()

    async def test_retry_on_502_then_succeed(self):
        call_count = 0

        async def fn(*a, **k):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return {"status": "error", "http_status": 502}
            return {"status": "ok", "http_status": 200}

        result = await with_retry(fn, max_attempts=5)
        assert result["status"] == "ok"
        assert call_count == 3

    async def test_do_not_retry_on_404(self):
        fn = AsyncMock(return_value={"status": "error", "http_status": 404})
        result = await with_retry(fn, max_attempts=3)
        assert result["http_status"] == 404
        fn.assert_called_once()

    async def test_exhaust_retries(self):
        fn = AsyncMock(return_value={"status": "error", "http_status": 502})
        result = await with_retry(fn, max_attempts=3)
        assert result["http_status"] == 502
        assert fn.call_count == 3

    async def test_retry_on_429(self):
        fn = AsyncMock(return_value={"status": "error", "http_status": 429})
        result = await with_retry(fn, max_attempts=2)
        assert fn.call_count == 2

    async def test_retry_on_503(self):
        fn = AsyncMock(return_value={"status": "error", "http_status": 503})
        result = await with_retry(fn, max_attempts=2)
        assert fn.call_count == 2

    async def test_retry_on_504(self):
        fn = AsyncMock(return_value={"status": "error", "http_status": 504})
        result = await with_retry(fn, max_attempts=2)
        assert fn.call_count == 2
