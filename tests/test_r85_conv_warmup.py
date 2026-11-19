"""R85 — pemuatan percakapan XChat wajib warmup embed dulu.

KASUS NYATA (19 Nov, diukur langsung di VPS): membuka halaman percakapan
langsung dari page baru menunggu chunk ondemand XChatEmbed dari server X —
27-79 detik, kadang timeout total (embed tak pernah termuat; checked=0
berjam-jam). Dengan satu navigasi warmup ke /i/chat dulu (memuat chunk ke
cache HTTP), percakapan dimuat 3.02 detik.

Kontrak (R85): unlock_and_read_xchat_conversation melakukan warmup
`/i/chat` pada konteks SEKALI (flag per konteks) sebelum goto percakapan.
Warmup tidak mengulang bila embed sudah termuat di halaman itu.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.xchat_e2ee as xee


class _FakeCtx:
    def __init__(self):
        self.pages = []
        self._warmed = False
        self.warmup_calls = 0

    @property
    def warmed(self) -> bool:
        return self._warmed

    def mark_warmed(self) -> None:
        self._warmed = True
        self.warmup_calls += 1

    async def new_page(self):
        page = _FakePage(self)
        self.pages.append(page)
        return page


class _FakePage:
    def __init__(self, ctx: "_FakeCtx"):
        self.ctx = ctx
        self.url = "about:blank"
        self.goto_calls: list[str] = []
        self.keyboard = MagicMock()
        self.keyboard.type = AsyncMock()
        self.keyboard.press = AsyncMock()
        self._embed_mounted = False
        self._rows = 0

        async def wait_for_function(fn, arg=None, timeout=None, **kw):
            # Semua wait mengembalikan sukses segera dengan nilai siap.
            return _Handle("ready")

        self.wait_for_function = wait_for_function

        async def evaluate(fn, *args, **kw):
            host = self._embed_mounted
            return {
                "gate": False,
                "links": 5 if host else 0,
            }

        self.evaluate = evaluate

    async def goto(self, url, **kw):
        self.goto_calls.append(url)
        self.url = url
        if url.rstrip("/").endswith("/i/chat"):
            self._embed_mounted = True
            self.ctx.mark_warmed()
        elif self.ctx._warmed:
            self._embed_mounted = True
            self._rows = 4
        return MagicMock(status=200)

    async def close(self):
        pass


class _Handle:
    def __init__(self, value):
        self._value = value

    async def json_value(self):
        return self._value


@pytest.mark.asyncio
async def test_conv_read_warms_up_embed_first(monkeypatch):
    ctx = _FakeCtx()
    calls = {"n": 0}

    async def fake_acquire(auth_token):
        calls["n"] += 1
        return ctx

    pool = MagicMock()
    pool.acquire = fake_acquire
    pool.release = AsyncMock()
    monkeypatch.setattr(xee.XChatContextPool, "get", lambda: pool)

    sem = MagicMock()
    sem.__aenter__ = AsyncMock(return_value=None)
    sem.__aexit__ = AsyncMock(return_value=False)
    pw = MagicMock()
    pw.semaphore = sem
    monkeypatch.setattr(xee.PlaywrightPool, "get", lambda: pw)
    monkeypatch.setattr(xee, "_ensure_pin_unlocked", AsyncMock(return_value=True))

    page_holder = {}

    async def capture_new_page():
        return await ctx.new_page()

    # intercept context.new_page via fake acquire ctx
    events = await xee.unlock_and_read_xchat_conversation(
        auth_token="tok", dm_pin="1234",
        conversation_id="1-2", my_user_id="1", max_results=30,
    )
    first_page = ctx.pages[0]
    assert first_page.goto_calls[0].rstrip("/").endswith("/i/chat"), (
        "goto pertama wajib warmup /i/chat, dapat %s" % first_page.goto_calls
    )
    assert any(c.endswith("/i/chat/1-2") for c in first_page.goto_calls), (
        "navigasi percakapan wajib terjadi setelah warmup"
    )


@pytest.mark.asyncio
async def test_warmup_only_once_per_context(monkeypatch):
    ctx = _FakeCtx()

    async def fake_acquire(auth_token):
        return ctx

    pool = MagicMock()
    pool.acquire = fake_acquire
    pool.release = AsyncMock()
    monkeypatch.setattr(xee.XChatContextPool, "get", lambda: pool)

    sem = MagicMock()
    sem.__aenter__ = AsyncMock(return_value=None)
    sem.__aexit__ = AsyncMock(return_value=False)
    pw = MagicMock()
    pw.semaphore = sem
    monkeypatch.setattr(xee.PlaywrightPool, "get", lambda: pw)
    monkeypatch.setattr(xee, "_ensure_pin_unlocked", AsyncMock(return_value=True))

    for _ in range(3):
        await xee.unlock_and_read_xchat_conversation(
            auth_token="tok", dm_pin="1234",
            conversation_id="1-2", my_user_id="1", max_results=30,
        )

    assert ctx.warmup_calls == 1, (
        "warmup /i/chat cukup SEKALI per konteks, terpanggil %d" % ctx.warmup_calls
    )
