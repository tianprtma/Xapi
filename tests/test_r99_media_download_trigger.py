"""R99 — picu unduhan media dengan membuka conv saat media masih pending.

KASUS NYATA (20 Nov, conv 1970506464105254912): menfess video "wots cantik
banget non greesel" terposting TEXT-ONLY. Video baru terunduh ke OPFS
dm_local_attachment SETELAH post — membaca OPFS saja tidak memicu unduhan;
membuka halaman conv yang memicu client mengunduh media pesan terbaru.
Media-pending timeout 45 menit (R80) keburu memposting teks sebelum video
terunduh.

Kontrak (R99):
- extract_xchat_opfs_db(force=True) melewati cache R95 (baca snapshot segar),
  dipakai setelah membuka conv agar media yang baru terunduh terlihat.
- Jalur OPFS membuka halaman conv + baca ulang (force) + recover lagi bila
  masih ada event media-pending (diverifikasi live; logika trigger inline).
"""
import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.xchat_e2ee as xee


@pytest.mark.asyncio
async def test_extract_force_bypasses_cache(monkeypatch):
    monkeypatch.setattr(xee, "_OPFS_DB_CACHE_TTL", 20.0)
    xee._OPFS_DB_CACHE.clear()
    ctx = type("Ctx", (), {})()
    page = MagicMock()
    page.evaluate = AsyncMock(
        return_value=base64.b64encode(b"SQLite format 3\x00" + b"\x00" * 50).decode())
    page.url = "https://x.com/i/chat"

    await xee.extract_xchat_opfs_db(page, "1", context=ctx)
    await xee.extract_xchat_opfs_db(page, "1", context=ctx)  # cache hit
    await xee.extract_xchat_opfs_db(page, "1", context=ctx, force=True)  # bypass
    assert page.evaluate.await_count == 2  # 1 awal + 1 force (cache hit tak evaluate)
    xee._OPFS_DB_CACHE.clear()


@pytest.mark.asyncio
async def test_extract_cache_hit_within_ttl(monkeypatch):
    monkeypatch.setattr(xee, "_OPFS_DB_CACHE_TTL", 20.0)
    xee._OPFS_DB_CACHE.clear()
    ctx = type("Ctx", (), {})()
    page = MagicMock()
    page.evaluate = AsyncMock(
        return_value=base64.b64encode(b"SQLite format 3\x00" + b"\x00" * 50).decode())
    page.url = "https://x.com/i/chat"

    await xee.extract_xchat_opfs_db(page, "1", context=ctx)
    await xee.extract_xchat_opfs_db(page, "1", context=ctx)
    assert page.evaluate.await_count == 1  # panggilan kedua pakai cache
    xee._OPFS_DB_CACHE.clear()