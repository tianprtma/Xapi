"""Tests for tid_provider.py — TIDProvider singleton and fallback logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tid_provider import TIDProvider


@pytest.mark.asyncio
class TestTIDProvider:
    async def test_singleton(self):
        p1 = TIDProvider.get()
        p2 = TIDProvider.get()
        assert p1 is p2

    async def test_initial_state(self):
        provider = TIDProvider()
        assert provider._ct is None
        assert provider._fallback_mode is False
        assert provider._refresh_failures == 0

    async def test_fallback_tid_format(self):
        provider = TIDProvider()
        tid = provider._fallback_tid("POST", "/test")
        assert tid.startswith("fallback-")

    async def test_stats_initial(self):
        provider = TIDProvider()
        stats = await provider.stats()
        assert stats["loaded"] is False
        assert stats["fallback_mode"] is False

    async def test_generate_stale_without_refresh(self):
        """When not loaded and refresh fails, generates fallback TID."""
        provider = TIDProvider()
        # Force stale state
        provider._loaded_at = 0
        provider._ct = None
        with patch.object(provider, "_refresh", side_effect=Exception("no network")):
            tid = await provider.generate("GET", "/test")
            assert tid.startswith("fallback-")

    async def test_fallback_mode_after_max_failures(self):
        provider = TIDProvider()
        provider._refresh_failures = 3
        provider._fallback_mode = True
        tid = await provider.generate("GET", "/test")
        assert tid.startswith("fallback-")

    async def test_not_stale_fallback_path(self):
        """When CT is loaded but run_in_executor fails, still generates fallback."""
        import time
        provider = TIDProvider()
        mock_ct = MagicMock()
        mock_ct.generate_transaction_id.side_effect = Exception("executor failed")
        provider._ct = mock_ct
        provider._loaded_at = time.time()
        provider._fallback_mode = True
        tid = await provider.generate("POST", "/test")
        assert tid.startswith("fallback-")
