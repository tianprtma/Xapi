"""R101 — trigger unduh media OPFS tahan race navigasi + retry.

KASUS NYATA: gambar menfess kadang tidak keposting karena (a) extract OPFS db
gagal saat halaman chat redirect ("Execution context was destroyed"), dan
(b) trigger unduh single goto+wait tidak me-render media terkubur.

Kontrak R101:
- extract_xchat_opfs_db retry evaluate saat error navigasi (context destroyed),
  bukan langsung raise; berhasil bila context akhirnya stabil.
- error non-navigasi tetap di-raise (tidak disembunyikan).
- bila semua retry navigasi gagal → None (bukan crash).
- trigger media punya budget retry (_MEDIA_TRIGGER_ATTEMPTS >= 1).
"""
import base64
import asyncio
from unittest.mock import AsyncMock

import pytest

import app.xchat_e2ee as xee


_FAKE_DB = b"SQLite format 3\x00" + b"\x00" * 64
_FAKE_B64 = base64.b64encode(_FAKE_DB).decode()


@pytest.mark.asyncio
async def test_extract_retries_on_navigation_error(monkeypatch):
    monkeypatch.setattr(xee.asyncio, "sleep", AsyncMock())
    calls = {"n": 0}

    class Page:
        async def evaluate(self, js, arg):
            calls["n"] += 1
            if calls["n"] < 3:
                raise Exception("Page.evaluate: Execution context was destroyed, "
                                "most likely because of a navigation")
            return _FAKE_B64

    out = await xee.extract_xchat_opfs_db(Page(), "123", force=True)
    assert out == _FAKE_DB
    assert calls["n"] == 3  # 2 gagal + 1 sukses


@pytest.mark.asyncio
async def test_extract_reraises_non_navigation_error(monkeypatch):
    monkeypatch.setattr(xee.asyncio, "sleep", AsyncMock())

    class Page:
        async def evaluate(self, js, arg):
            raise ValueError("boom")

    with pytest.raises(ValueError):
        await xee.extract_xchat_opfs_db(Page(), "123", force=True)


@pytest.mark.asyncio
async def test_extract_returns_none_after_exhausting_navigation_retries(monkeypatch):
    monkeypatch.setattr(xee.asyncio, "sleep", AsyncMock())

    class Page:
        async def evaluate(self, js, arg):
            raise Exception("Execution context was destroyed")

    out = await xee.extract_xchat_opfs_db(Page(), "123", force=True)
    assert out is None


def test_media_trigger_attempts_budget():
    assert xee._MEDIA_TRIGGER_ATTEMPTS >= 1