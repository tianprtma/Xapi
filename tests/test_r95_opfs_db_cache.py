"""R95 — cache bytes db OPFS per konteks (TTL pendek) mempercepat watch.

Bottleneck siklus: tiap fetch percakapan watch membaca ulang file SQLite OPFS
18MB via page.evaluate (~15-20s antri semaphore browser); 16 conv → fase fetch
3-4 menit. Semua conv berbagi file db yang SAMA, jadi membaca ulang per conv
mubazir. Cache bytes db per (context, viewer) dengan TTL pendek membuat conv
dalam satu burst berbagi snapshot; freshness disegarkan tiap TTL.

Kontrak (R95):
- extract_xchat_opfs_db dengan context menyimpan bytes ke cache TTL; panggilan
  berikut dalam TTL mengembalikan bytes cache TANPA page.evaluate lagi.
- Setelah TTL kedaluwarsa, baca ulang (evaluate dipanggil lagi).
- viewer_id berbeda = kunci cache berbeda.
- TTL 0 menonaktifkan cache (perilaku lama).
"""
import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.xchat_e2ee as xee

DB = b"SQLite format 3\x00" + b"\x00" * 100
B64 = base64.b64encode(DB).decode()


def _ctx():
    # Objek polos (bukan MagicMock) agar getattr(_xchat_opfs_page) = None
    # dan penyimpanan cache page tidak memicu atribut auto-MagicMock.
    return type("Ctx", (), {})()


def _page():
    p = MagicMock()
    p.evaluate = AsyncMock(return_value=B64)
    p.url = "https://x.com/i/chat"
    return p


@pytest.fixture(autouse=True)
def _clear_cache():
    xee._OPFS_DB_CACHE.clear()
    yield
    xee._OPFS_DB_CACHE.clear()


@pytest.mark.asyncio
async def test_cache_hit_skips_evaluate(monkeypatch):
    monkeypatch.setattr(xee, "_OPFS_DB_CACHE_TTL", 20.0)
    ctx = _ctx()
    page = _page()

    d1 = await xee.extract_xchat_opfs_db(page, "1", context=ctx)
    d2 = await xee.extract_xchat_opfs_db(page, "1", context=ctx)

    assert d1 == DB and d2 == DB
    assert page.evaluate.await_count == 1, "panggilan kedua dalam TTL wajib pakai cache"


@pytest.mark.asyncio
async def test_cache_expires(monkeypatch):
    monkeypatch.setattr(xee, "_OPFS_DB_CACHE_TTL", 20.0)
    clock = {"t": 1000.0}
    monkeypatch.setattr(xee.time, "monotonic", lambda: clock["t"])
    ctx = _ctx()
    page = _page()

    await xee.extract_xchat_opfs_db(page, "1", context=ctx)
    clock["t"] += 25.0  # lewat TTL
    await xee.extract_xchat_opfs_db(page, "1", context=ctx)

    assert page.evaluate.await_count == 2, "setelah TTL wajib baca ulang"


@pytest.mark.asyncio
async def test_different_viewer_separate_cache(monkeypatch):
    monkeypatch.setattr(xee, "_OPFS_DB_CACHE_TTL", 20.0)
    ctx = _ctx()
    page = _page()

    await xee.extract_xchat_opfs_db(page, "1", context=ctx)
    await xee.extract_xchat_opfs_db(page, "2", context=ctx)

    assert page.evaluate.await_count == 2


@pytest.mark.asyncio
async def test_ttl_zero_disables_cache(monkeypatch):
    monkeypatch.setattr(xee, "_OPFS_DB_CACHE_TTL", 0.0)
    ctx = _ctx()
    page = _page()

    await xee.extract_xchat_opfs_db(page, "1", context=ctx)
    await xee.extract_xchat_opfs_db(page, "1", context=ctx)

    assert page.evaluate.await_count == 2