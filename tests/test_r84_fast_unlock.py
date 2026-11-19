"""R84 — konfirmasi 'ready' XChat tidak boleh membayar settle-window 2.5s
di SETIAP fetch.

KASUS NYATA (19 Nov): bacaan percakapan XChat melambat 27-58s/fetch.
Porsi tetap yang bisa dihilangkan: setelah `wait_for_function` menyatakan
'ready', kode menunggu `asyncio.sleep(2.5)` untuk mengecek gate PIN
transient SETIAP KALI — padahal profil persistent sudah lama unlocked.
Total sleep tetap per fetch: 2.5s (settle) + 0.6s + 2×0.4s + scroll.

Kontrak baru (R84):
- Saat state 'ready' DAN URL bukan /pin/ DAN ada link percakapan ≥ 1:
  konfirmasi gate dilakukan dengan poll CEPAT (wait_for_function 1200ms
  'stable-ready') alih-alih sleep mati 2.5s — pin transient tetap
  terdeteksi (gate muncul → wait mengembalikan 'pin').
- 'ready' tanpa link apa pun (shell kosong) tetap jalur lama penuh.
- Unlock PIN (jalur 'pin') tidak diubah — keamanan E2EE di atas kecepatan.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.xchat_e2ee as xee


class _FakeWaitHandle:
    def __init__(self, value: str):
        self._value = value

    async def json_value(self) -> str:
        return self._value


def _make_page(url: str, *, ready: bool, links: int, gate: bool = False) -> MagicMock:
    page = MagicMock()
    page.url = url
    calls = {"n": 0}

    async def wait_for_function(fn, arg=None, timeout=None, **kw):
        calls["n"] += 1
        # Emulasi: panggilan pertama mengembalikan state awal 'ready';
        # jika stable-check dipoll ulang, kembalikan kondisi gate/links.
        if calls["n"] == 1:
            return _FakeWaitHandle("ready")
        return _FakeWaitHandle("pin" if gate else "ready")

    page.wait_for_function = wait_for_function

    async def evaluate(fn, *args, **kw):
        # Selalu laporkan kondisi DOM terkini (dipakai konfirmasi lama & baru)
        return {"gate": gate, "links": links}

    page.evaluate = evaluate
    page.keyboard = MagicMock()
    page.keyboard.type = AsyncMock()
    page.keyboard.press = AsyncMock()
    return page


@pytest.mark.asyncio
async def test_ready_with_links_skips_dead_sleep(monkeypatch):
    """Konv biasa (ready + ada link): tidak ada asyncio.sleep(2.5) — deteksi
    pin transient memakai poll cepat; total settle ≤ 1.5s."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(sec: float):
        sleeps.append(sec)
        await real_sleep(0)

    monkeypatch.setattr(xee.asyncio, "sleep", spy_sleep)
    page = _make_page("https://x.com/i/chat/123-456", ready=True, links=7)

    ok = await xee._ensure_pin_unlocked(page, "1234")

    assert ok is True
    assert 2.5 not in sleeps, "settle-window mati 2.5s tidak boleh dibayar pada jalur ready+links"
    assert sum(sleeps) <= 1.6, "total settle sleep harus <= 1.5s + toleransi, dapat %s" % sleeps


@pytest.mark.asyncio
async def test_ready_with_links_still_catches_transient_pin(monkeypatch):
    """Gate PIN transient yang menyusul tetap HARUS terdeteksi (ready
    prematur): poll cepat mengembalikan 'pin' → kode lanjut mengetik PIN."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(sec: float):
        sleeps.append(sec)
        await real_sleep(0)

    monkeypatch.setattr(xee.asyncio, "sleep", spy_sleep)
    page = _make_page("https://x.com/i/chat/123-456", ready=True, links=7, gate=True)
    # setelah gate terdeteksi, wait inputs langsung sukses, enter, dan
    # dm-container muncul — semua via wait_for_function default mock
    typed = {"digits": []}

    async def type_key(key, delay=0):
        typed["digits"].append(key)

    page.keyboard.type = type_key

    ok = await xee._ensure_pin_unlocked(page, "1234")

    assert ok is True
    assert typed["digits"] == list("1234"), "PIN tetap diketik saat gate transient muncul"


@pytest.mark.asyncio
async def test_empty_shell_ready_keeps_cautious_path(monkeypatch):
    """'ready' TANPA link (shell kosong, kemungkinan gate menyusul) tetap
    memakai jalur hati-hati lama — keamanan di atas kecepatan."""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def spy_sleep(sec: float):
        sleeps.append(sec)
        await real_sleep(0)

    monkeypatch.setattr(xee.asyncio, "sleep", spy_sleep)
    page = _make_page("https://x.com/i/chat/123-456", ready=True, links=0, gate=True)

    ok = await xee._ensure_pin_unlocked(page, "1234")

    # Jalur lama: state dipaksa 'pin' → mengetik PIN, sukses unlock.
    assert ok is True
