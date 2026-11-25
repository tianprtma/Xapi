"""
Headless browser fallback untuk tweet search.

X.com gate endpoint search (SearchTimeline & adaptive.json) dengan
header `x-client-transaction-id` yang di-generate sisi browser.
Daripada port logic generator-nya, kita pakai Chromium asli via Playwright,
intercept response GraphQL/adaptive.json, return JSON-nya.

Trade-off:
- Lambat: ~3-6 detik per query (page load + render)
- Berat: butuh Chromium binary (~300MB)
- Reliable: persis apa yang dilihat browser asli

Concurrency: PLAYWRIGHT_MAX_CONCURRENT (default 4) batasi number of pages
yang aktif paralel — di luar limit, request antri di asyncio.Semaphore.
Tanpa cap, headless Chrome bisa OOM saat >10 concurrent pages.

In-flight coalescing: identical concurrent requests (same op + token + vars)
share a single browser page. The first caller runs the operation; waiters
receive the same result when the page finishes. Eliminates redundant ~3-6s
headless Chrome calls when e.g. a worker fan-out hits the same endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Coroutine, Literal, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Response,
    async_playwright,
)

log = logging.getLogger(__name__)

SearchType = Literal["Latest", "Top", "People", "Media"]

# Map ke parameter ?f= di URL x.com/search
URL_FILTER = {
    "Latest": "live",
    "Top": "top",
    "People": "user",
    "Media": "image",
}

# Cap concurrent Playwright operations (browser pages aktif). Default 1 —
# fallback profil jarang terpakai, dan headless Chrome ~250MB + 80-150MB
# per halaman tambahan. Naikkan via env hanya jika VPS RAM besar.
PLAYWRIGHT_MAX_CONCURRENT = int(os.environ.get("PLAYWRIGHT_MAX_CONCURRENT", "1"))

# Master switch seluruh jalur Playwright (search fallback + TID via browser).
# Default 0: headless Chrome ~300MB + driver node 130MB per launch, dan di
# VPS tanpa binary Chromium jalur ini selalu gagal. Set PLAYWRIGHT_ENABLED=1
# hanya jika binary terinstall dan fallback memang diinginkan.
PLAYWRIGHT_ENABLED = os.environ.get("PLAYWRIGHT_ENABLED", "0") == "1"


# ──────────────────────────── In-flight coalescer ────────────────────────────


class _Flight:
    __slots__ = ("event", "result", "exc")

    def __init__(self) -> None:
        self.event = asyncio.Event()
        self.result: dict[str, Any] | None = None
        self.exc: BaseException | None = None


class _InFlightCoalescer:
    """Deduplicate identical concurrent Playwright calls.

    Two callers asking for the same (op, key, vars) at the same time share
    one page — the second caller waits for the first's result instead of
    spawning its own Chromium page (saving ~80-150MB + 3-6s).
    """

    def __init__(self) -> None:
        self._pending: dict[str, _Flight] = {}
        self._lock = asyncio.Lock()

    async def run(
        self,
        key: str,
        fn: Callable[[], Coroutine[Any, Any, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Execute `fn()` once per unique `key` across concurrent callers.

        If another caller is already executing for this key, wait for its
        result. Otherwise execute and broadcast.
        """
        async with self._lock:
            flight = self._pending.get(key)
            is_owner = flight is None
            if is_owner:
                flight = _Flight()
                self._pending[key] = flight

        if not is_owner:
            # Waiter path: block until executor finishes, then read from flight
            await flight.event.wait()
            if flight.exc is not None:
                if isinstance(flight.exc, asyncio.CancelledError):
                    # Owner was cancelled (e.g. client disconnect) — take over execution
                    # rather than cascading CancelledError into an innocent waiter.
                    return await self.run(key, fn)
                raise flight.exc
            if flight.result is None:
                raise RuntimeError(f"coalesced call for {key} failed upstream")
            return flight.result

        # Executor path: run fn(), store result (or exception) on flight, wake waiters
        try:
            result = await fn()
            flight.result = result
            return result
        except BaseException as e:
            flight.exc = e
            raise
        finally:
            async with self._lock:
                self._pending.pop(key, None)
                flight.event.set()


_coalescer = _InFlightCoalescer()


def _proxy_tag(auth_token: str) -> str:
    from app.config import proxy_for_token
    p = proxy_for_token(auth_token)
    if not p:
        return "direct"
    return hashlib.sha256(p.encode("utf-8")).hexdigest()[:12]


def _search_key(auth_token: str, q: str, search_type: SearchType) -> str:
    from app.config import token_key
    return f"search:{token_key(auth_token)}:{_proxy_tag(auth_token)}:{q}:{search_type}"


def _fetch_key(auth_token: str, navigate_url: str, match_path: str | list[str], click_selector: str | None = None) -> str:
    from app.config import token_key
    cs = click_selector or ""
    mp = match_path if isinstance(match_path, str) else "|".join(sorted(match_path))
    return f"fetch:{token_key(auth_token)}:{_proxy_tag(auth_token)}:{navigate_url}:{mp}:{cs}"


def _click_key(
    auth_token: str,
    navigate_url: str,
    click_selector: str,
    match_response_substr: str | list[str] | None = None,
    confirm_selector: str | None = None,
) -> str:
    from app.config import token_key
    mr = ""
    if match_response_substr:
        mr = match_response_substr if isinstance(match_response_substr, str) else "|".join(sorted(match_response_substr))
    return f"click:{token_key(auth_token)}:{_proxy_tag(auth_token)}:{navigate_url}:{click_selector}:{confirm_selector or ''}:{mr}"


class PlaywrightPool:
    """Singleton browser instance — launch sekali, share antar request.

    Tambah semaphore untuk cap concurrent page operations.
    """

    _instance: Optional["PlaywrightPool"] = None

    # Setelah N launch gagal beruntun, jalur browser dimatikan permanen untuk
    # umur proses — mencegah spawn driver node (130MB) berulang kali saat
    # binary Chromium tidak tersedia.
    MAX_LAUNCH_FAILURES = 3

    def __init__(self) -> None:
        self._pw = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(PLAYWRIGHT_MAX_CONCURRENT)
        self._launch_failures = 0
        self._disabled = False

    @classmethod
    def get(cls) -> "PlaywrightPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._sem

    async def ensure(self) -> Browser:
        if not PLAYWRIGHT_ENABLED:
            raise RuntimeError(
                "Playwright disabled (PLAYWRIGHT_ENABLED!=1) — "
                "jalur browser fallback tidak tersedia"
            )
        if self._disabled:
            raise RuntimeError(
                "Playwright permanently disabled after repeated launch failures"
            )
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            if self._browser is not None:
                # Clear pooled contexts bound to the dead/restarting browser/driver
                # so ContextPool/XChatContextPool never hand back orphaned contexts.
                if XChatContextPool._instance is not None:
                    try:
                        await XChatContextPool._instance.close_all()
                    except Exception:  # noqa: BLE001
                        pass
                if ContextPool._instance is not None:
                    try:
                        await ContextPool._instance.close_all()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    await self._browser.close()
                except Exception:  # noqa: BLE001
                    pass
                self._browser = None
            if self._pw is not None:
                try:
                    await self._pw.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._pw = None
            try:
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
                self._launch_failures = 0
                return self._browser
            except Exception:
                # Stop driver node yang baru di-start supaya tidak jadi
                # proses yatim 130MB; hitung kegagalan untuk hard-disable.
                if self._pw is not None:
                    try:
                        await self._pw.stop()
                    except Exception:  # noqa: BLE001
                        pass
                    self._pw = None
                self._browser = None
                self._launch_failures += 1
                if self._launch_failures >= self.MAX_LAUNCH_FAILURES:
                    self._disabled = True
                    log.error(
                        "Playwright launch failed %dx — browser fallback "
                        "disabled for this process",
                        self._launch_failures,
                    )
                raise

    async def driver(self):
        """Return the Playwright driver (starts shared driver + browser first).

        Dipakai XChatContextPool untuk `launch_persistent_context` — API
        persistent context hidup di BrowserType (driver), bukan di Browser.
        """
        await self.ensure()
        return self._pw

    async def warmup(self) -> None:
        """Pre-launch browser di startup supaya request pertama tidak nunggu Chromium init.

        No-op ketika Playwright dimatikan via env — jangan spawn driver
        node hanya untuk langsung gagal (dan sebelumnya: bocor).
        """
        if not PLAYWRIGHT_ENABLED:
            return
        try:
            await self.ensure()
        except Exception:  # noqa: BLE001
            pass

    async def close(self) -> None:
        if XChatContextPool._instance is not None:
            try:
                await XChatContextPool._instance.close_all()
            except Exception:  # noqa: BLE001
                pass
        if ContextPool._instance is not None:
            try:
                await ContextPool._instance.close_all()
            except Exception:  # noqa: BLE001
                pass
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:  # noqa: BLE001
                    pass
                self._browser = None
            if self._pw is not None:
                try:
                    await self._pw.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._pw = None


async def _new_context(browser: Browser, auth_token: str) -> BrowserContext:
    from app.config import gen_ct0, playwright_proxy_for_token, profile_for_token

    prof = profile_for_token(auth_token)
    ua = prof["user_agent"]
    is_win = "Windows" in prof["sec_ch_ua_platform"]
    ctx_kwargs: dict[str, Any] = {
        "user_agent": ua,
        "viewport": {"width": 1366, "height": 768} if is_win else {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "extra_http_headers": {
            "sec-ch-ua": prof["sec_ch_ua"],
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": prof["sec_ch_ua_platform"],
        },
    }
    pw_proxy = playwright_proxy_for_token(auth_token)
    if pw_proxy:
        ctx_kwargs["proxy"] = pw_proxy
    context = await browser.new_context(**ctx_kwargs)
    try:
        # Stealth init script: sembunyikan indikator headless Chrome / Playwright
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = window.chrome || { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
            """
        )
        # ct0 — X CSRF token, needed by ton.twitter.com alongside auth_token
        _ct0 = gen_ct0()
        await context.add_cookies(
            [
                {
                    "name": "auth_token",
                    "value": auth_token,
                    "domain": ".x.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None",
                },
                {
                    "name": "auth_token",
                    "value": auth_token,
                    "domain": ".twitter.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None",
                },
                {
                    "name": "ct0",
                    "value": _ct0,
                    "domain": ".x.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "Lax",
                },
                {
                    "name": "ct0",
                    "value": _ct0,
                    "domain": ".twitter.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "None",
                },
            ]
        )
    except BaseException:
        try:
            await context.close()
        except Exception:  # noqa: BLE001
            pass
        raise
    return context


class ContextPool:
    """
    LRU pool BrowserContext per auth_token. Reuse → skip 2-3 detik
    context init + cookie injection per request. Cap 5 context; evict LRU.
    """

    _instance: Optional["ContextPool"] = None
    MAX = 5

    def __init__(self) -> None:
        self._ctxs: dict[str, tuple[BrowserContext, float]] = {}
        # id(ctx) -> jumlah holder. Key id() aman: context yang dihitung selalu
        # dirujuk _ctxs atau _dropped, jadi tidak ada aliasing id reuse.
        self._ctx_use: dict[int, int] = {}
        # Context dihapus dari pool saat masih dipakai (invalidate) — ditutup
        # saat holder terakhir release().
        self._dropped: set = set()
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> "ContextPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _ctx_key(auth_token: str) -> str:
        from app.config import proxy_for_token

        proxy = proxy_for_token(auth_token)
        if not proxy:
            return auth_token
        phash = hashlib.sha256(proxy.encode("utf-8")).hexdigest()[:12]
        return f"{auth_token}:p:{phash}"

    async def acquire(self, auth_token: str) -> BrowserContext:
        import time as _t
        ctx_key = self._ctx_key(auth_token)
        async with self._lock:
            entry = self._ctxs.get(ctx_key)
            if entry:
                ctx, _ = entry
                # health check: verify browser is still connected (ctx.pages alone
                # returns [] on a closed context/browser without raising).
                try:
                    _ = ctx.pages
                    br = getattr(ctx, "browser", None)
                    if br is not None and hasattr(br, "is_connected") and not br.is_connected():
                        raise RuntimeError("browser disconnected")
                    self._ctxs[ctx_key] = (ctx, _t.time())
                    self._ctx_use[id(ctx)] = self._ctx_use.get(id(ctx), 0) + 1
                    return ctx
                except Exception:  # noqa: BLE001
                    self._ctxs.pop(ctx_key, None)
                    self._ctx_use.pop(id(ctx), None)

            browser = await PlaywrightPool.get().ensure()
            ctx = await _new_context(browser, auth_token)

            while len(self._ctxs) >= self.MAX:
                # Evict context idle terlama — skip yang sedang dipakai;
                # pool boleh melebihi MAX sementara daripada menutup context
                # yang sedang dipakai coroutine lain.
                candidates = [
                    (k, ts) for k, (c, ts) in self._ctxs.items()
                    if self._ctx_use.get(id(c), 0) == 0
                ]
                if not candidates:
                    break
                oldest = min(candidates, key=lambda kv: kv[1])[0]
                old_ctx, _ = self._ctxs.pop(oldest)
                self._ctx_use.pop(id(old_ctx), None)
                self._dropped.discard(old_ctx)
                try:
                    await old_ctx.close()
                except Exception:  # noqa: BLE001
                    pass

            self._ctxs[ctx_key] = (ctx, _t.time())
            self._ctx_use[id(ctx)] = self._ctx_use.get(id(ctx), 0) + 1
            return ctx

    async def release(self, auth_token: str, ctx: BrowserContext) -> None:
        """Decrement holder count untuk `ctx`; tutup context yang di-drop
        dari pool saat masih dipakai (invalidate) ketika holder terakhir
        selesai."""
        async with self._lock:
            count = self._ctx_use.get(id(ctx), 0)
            if count > 1:
                self._ctx_use[id(ctx)] = count - 1
                return
            self._ctx_use.pop(id(ctx), None)
            dropped = ctx in self._dropped
            if dropped:
                self._dropped.discard(ctx)
        if dropped:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass

    async def invalidate(self, auth_token: str, *, all_proxies: bool = True) -> None:
        prefix = f"{auth_token}:p:"
        target_key = None if all_proxies else self._ctx_key(auth_token)
        async with self._lock:
            if target_key is not None:
                keys = [target_key] if target_key in self._ctxs else []
            else:
                keys = [k for k in self._ctxs if k == auth_token or k.startswith(prefix)]
            for k in keys:
                entry = self._ctxs.pop(k, None)
                if entry and self._ctx_use.get(id(entry[0]), 0) > 0:
                    # Context sedang dipakai — keluar dari pool (pemanggil baru
                    # dapat context baru), close ditunda sampai holder terakhir
                    # release(). Counter _ctx_use tidak di-reset agar drain
                    # alami saat holder melepas.
                    self._dropped.add(entry[0])
                    continue
                if entry:
                    self._ctx_use.pop(id(entry[0]), None)
                    try:
                        await entry[0].close()
                    except Exception:  # noqa: BLE001
                        pass

    async def close_all(self) -> None:
        async with self._lock:
            ctxs = [c for c, _ in self._ctxs.values()] + list(self._dropped)
            self._ctxs.clear()
            self._ctx_use.clear()
            self._dropped.clear()
        for ctx in ctxs:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass

    def stats(self) -> dict[str, int]:
        return {"contexts": len(self._ctxs), "max": self.MAX}


# ──────────────────────────── XChat persistent profile ────────────────────────────


# Unlock E2EE XChat tersimpan di storage browser (localStorage/IndexedDB
# origin x.com). Profil on-disk per akun → PIN cukup dimasukkan SEKALI,
# run/proses berikutnya langsung ke inbox tanpa gate.
XCHAT_PROFILE_DIR: str = os.environ.get(
    "XCHAT_PROFILE_DIR", str(Path(__file__).resolve().parent / ".xchat_profiles")
)
XCHAT_PERSISTENT_MAX: int = int(os.environ.get("XCHAT_PERSISTENT_MAX", "3"))


XCHAT_HEADLESS = os.environ.get("XCHAT_HEADLESS", "1") != "0"


def _xchat_profile_dir(auth_token: str) -> Path:
    """Subdir profil per akun — hash TANPA salt agar stabil antar restart
    (token_key memakai salt per-proses yang berubah tiap restart)."""
    import hashlib

    digest = hashlib.sha256(f"xchat:{auth_token}".encode()).hexdigest()[:16]
    return Path(XCHAT_PROFILE_DIR) / digest


async def _apply_session_cookies(ctx: BrowserContext, auth_token: str, ct0: Optional[str] = None) -> None:
    """Inject cookie sesi (auth_token + ct0) — overwrite aman jika sudah ada."""
    from app.config import gen_ct0

    _ct0 = ct0 or gen_ct0()
    await ctx.add_cookies(
        [
            {
                "name": "auth_token",
                "value": auth_token,
                "domain": ".x.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            },
            {
                "name": "auth_token",
                "value": auth_token,
                "domain": ".twitter.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            },
            {
                "name": "ct0",
                "value": _ct0,
                "domain": ".x.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            },
            {
                "name": "ct0",
                "value": _ct0,
                "domain": ".twitter.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "None",
            },
        ]
    )


class XChatContextPool:
    """Pool BrowserContext PERSISTENT (profil on-disk) khusus alur XChat E2EE.

    - Satu profil disk per auth_token (hash stabil) → unlock PIN bertahan
      antar run/proses; PIN hanya dimasukkan sekali per akun.
    - `launch_persistent_context` memproses SATU browser process per context —
      jumlah dibatasi XCHAT_PERSISTENT_MAX; LRU idle di-evict dengan in-use
      tracking (materi sama dengan ContextPool). Evict aman: unlock state
      ada di disk, re-launch tidak minta PIN ulang.
    - CATATAN: profil menyimpan cookie sesi (auth_token) + kunci E2EE di
      disk — lindungi direktorinya (default: <repo>/.xchat_profiles).
    - Asumsi single-process (WORKER=1) — dua proses tidak boleh membuka
      profil dir yang sama secara bersamaan.
    """

    _instance: Optional["XChatContextPool"] = None

    def __init__(self) -> None:
        self._ctxs: OrderedDict[str, BrowserContext] = OrderedDict()  # key = hash
        self._ctx_use: dict[int, int] = {}   # id(ctx) -> jumlah holder
        self._ctx_keys: dict[int, str] = {}  # id(ctx) -> key (untuk drain close_all)
        self._ctx_proxy: dict[str, Optional[str]] = {}  # key -> proxy URL aktif
        self._proxy_switch_waiters: dict[str, int] = {}  # key -> waiter ganti proxy (anti starvation)
        self._closing_count: dict[str, int] = {}  # key -> context yg sedang drain/close (anti SingletonLock race)
        self._idle_events: dict[str, asyncio.Event] = {}  # key -> notif saat context idle/closed
        self._dropped: set = set()           # dihapus saat masih dipakai
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> "XChatContextPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def acquire(self, auth_token: str) -> BrowserContext:
        from app.config import gen_ct0, playwright_proxy_for_token, profile_for_token, proxy_for_token

        key = hashlib.sha256(f"xchat:{auth_token}".encode()).hexdigest()[:16]
        profile_dir = _xchat_profile_dir(auth_token)
        ct0_file = profile_dir / "ct0.txt"
        desired_proxy = proxy_for_token(auth_token)
        pw_proxy = playwright_proxy_for_token(auth_token)

        deadline = asyncio.get_running_loop().time() + 30.0
        while True:
            wait_ev: Optional[asyncio.Event] = None
            is_proxy_switch_waiter = False
            async with self._lock:
                # ct0 STABIL per profil — baca/tulis di dalam lock agar concurrent
                # first-time acquire tidak menulis ct0 yang saling bentrok.
                ct0 = None
                if ct0_file.is_file():
                    ct0 = ct0_file.read_text().strip() or None
                if not ct0:
                    ct0 = gen_ct0()
                    profile_dir.mkdir(parents=True, exist_ok=True)
                    ct0_file.write_text(ct0)

                ctx = self._ctxs.get(key)
                if self._closing_count.get(key, 0) > 0:
                    # Context lama untuk profile_dir ini masih proses close() —
                    # wajib tunggu selesai agar tidak menabrak Chromium SingletonLock.
                    wait_ev = self._idle_events.get(key)
                    if wait_ev is None or wait_ev.is_set():
                        wait_ev = asyncio.Event()
                        self._idle_events[key] = wait_ev
                elif ctx is not None and self._ctx_proxy.get(key) != desired_proxy:
                    if self._ctx_use.get(id(ctx), 0) > 0:
                        # Context sedang dipakai dengan proxy berbeda — tunggu
                        # holder selesai agar tidak pernah membocorkan IP salah.
                        wait_ev = self._idle_events.get(key)
                        if wait_ev is None or wait_ev.is_set():
                            wait_ev = asyncio.Event()
                            self._idle_events[key] = wait_ev
                        self._proxy_switch_waiters[key] = self._proxy_switch_waiters.get(key, 0) + 1
                        is_proxy_switch_waiter = True
                    else:
                        self._ctxs.pop(key, None)
                        self._ctx_proxy.pop(key, None)
                        self._ctx_use.pop(id(ctx), None)
                        self._ctx_keys.pop(id(ctx), None)
                        try:
                            await ctx.close()
                        except Exception:  # noqa: BLE001
                            pass
                        ctx = None
                elif (
                    ctx is not None
                    and self._ctx_use.get(id(ctx), 0) > 0
                    and self._proxy_switch_waiters.get(key, 0) > 0
                ):
                    # Jangan biarkan arus request proxy lama membuat waiter ganti-proxy kelaparan.
                    wait_ev = self._idle_events.get(key)
                    if wait_ev is None or wait_ev.is_set():
                        wait_ev = asyncio.Event()
                        self._idle_events[key] = wait_ev
                if wait_ev is None:
                    if ctx is not None:
                        # health check: context yang sudah mati melempar di .pages / add_cookies
                        try:
                            _ = ctx.pages
                            await _apply_session_cookies(ctx, auth_token, ct0)
                            self._ctxs.move_to_end(key)
                            self._ctx_use[id(ctx)] = self._ctx_use.get(id(ctx), 0) + 1
                            return ctx
                        except Exception:  # noqa: BLE001
                            self._ctxs.pop(key, None)
                            self._ctx_proxy.pop(key, None)
                            if self._ctx_use.get(id(ctx), 0) > 0:
                                self._dropped.add(ctx)
                                self._closing_count[key] = self._closing_count.get(key, 0) + 1
                                wait_ev = self._idle_events.get(key)
                                if wait_ev is None or wait_ev.is_set():
                                    wait_ev = asyncio.Event()
                                    self._idle_events[key] = wait_ev
                            else:
                                self._ctx_use.pop(id(ctx), None)
                                self._ctx_keys.pop(id(ctx), None)
                                try:
                                    await ctx.close()
                                except Exception:  # noqa: BLE001
                                    pass
                                ctx = None
                if wait_ev is None:
                    prof = profile_for_token(auth_token)
                    is_win = "Windows" in prof["sec_ch_ua_platform"]
                    profile_dir.mkdir(parents=True, exist_ok=True)

                    driver = await PlaywrightPool.get().driver()
                    launch_kwargs: dict[str, Any] = {
                        "headless": XCHAT_HEADLESS,
                        "user_agent": prof["user_agent"],
                        "viewport": {"width": 1366, "height": 768} if is_win else {"width": 1440, "height": 900},
                        "locale": "en-US",
                        "timezone_id": "America/New_York",
                        "extra_http_headers": {
                            "sec-ch-ua": prof["sec_ch_ua"],
                            "sec-ch-ua-mobile": "?0",
                            "sec-ch-ua-platform": prof["sec_ch_ua_platform"],
                        },
                        "args": [
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                        ],
                    }
                    if pw_proxy:
                        launch_kwargs["proxy"] = pw_proxy
                    try:
                        ctx = await driver.chromium.launch_persistent_context(
                            str(profile_dir),
                            **launch_kwargs,
                        )
                    except Exception as exc:  # noqa: BLE001
                        from app.config import redact_proxy_creds
                        raise RuntimeError(
                            f"XChat profile '{profile_dir.name}' gagal dibuka — "
                            f"profil terkunci oleh proses lain (server & fetch_dm_pin.py "
                            f"bareng?) atau Chromium gagal launch: {type(exc).__name__}: "
                            f"{redact_proxy_creds(str(exc))}"
                        ) from exc
                    try:
                        await ctx.add_init_script(
                            """
                            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                            Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                            Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
                            Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
                            window.chrome = window.chrome || { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
                            // R106: spoof WebGL renderer — SwiftShader (software headless) adalah
                            // sinyal anti-bot kuat; X chat menolak me-render konten dengannya.
                            const spoofGL = (proto) => {
                                if (!proto) return;
                                const orig = proto.getParameter;
                                proto.getParameter = function(p) {
                                    const dbg = this.getExtension && this.getExtension('WEBGL_debug_renderer_info');
                                    if (dbg && p === dbg.UNMASKED_VENDOR_WEBGL) return 'Google Inc. (Intel)';
                                    if (dbg && p === dbg.UNMASKED_RENDERER_WEBGL) return 'ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)';
                                    return orig.apply(this, arguments);
                                };
                            };
                            try { spoofGL(WebGLRenderingContext.prototype); } catch(e) {}
                            try { spoofGL(WebGL2RenderingContext.prototype); } catch(e) {}
                            try {
                                const origQuery = window.navigator.permissions && window.navigator.permissions.query;
                                if (origQuery) window.navigator.permissions.query = (p) => (
                                    p && p.name === 'notifications'
                                        ? Promise.resolve({ state: Notification.permission })
                                        : origQuery(p));
                            } catch(e) {}
                            try {
                                Object.defineProperty(screen, 'width', { get: () => 1440 });
                                Object.defineProperty(screen, 'height', { get: () => 900 });
                                Object.defineProperty(screen, 'availWidth', { get: () => 1440 });
                                Object.defineProperty(screen, 'availHeight', { get: () => 900 });
                                Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
                                Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });
                            } catch(e) {}
                            """
                        )
                        await _apply_session_cookies(ctx, auth_token, ct0)
                    except BaseException:
                        # Tutup persistent context bila init gagal/cancel agar proses
                        # Chromium dan SingletonLock tidak bocor permanen.
                        try:
                            await ctx.close()
                        except Exception:  # noqa: BLE001
                            pass
                        raise

                    self._ctxs[key] = ctx
                    self._ctx_proxy[key] = desired_proxy
                    self._ctx_keys[id(ctx)] = key
                    self._ctx_use[id(ctx)] = self._ctx_use.get(id(ctx), 0) + 1

                    # Evict LRU idle bila melebihi cap (persistent: aman, state di disk)
                    while len(self._ctxs) > XCHAT_PERSISTENT_MAX:
                        evict_key = next(
                            (k for k, c in self._ctxs.items() if self._ctx_use.get(id(c), 0) == 0),
                            None,
                        )
                        if evict_key is None:
                            break  # semua in-use — biarkan melebihi cap sementara
                        old = self._ctxs.pop(evict_key)
                        self._ctx_proxy.pop(evict_key, None)
                        self._ctx_use.pop(id(old), None)
                        self._ctx_keys.pop(id(old), None)
                        self._dropped.discard(old)
                        try:
                            await old.close()
                        except Exception:  # noqa: BLE001
                            pass

                    return ctx

            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise RuntimeError(
                        "XChat context sedang dipakai dengan proxy berbeda dan belum idle"
                    )
                try:
                    await asyncio.wait_for(wait_ev.wait(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise RuntimeError(
                        "XChat context sedang dipakai dengan proxy berbeda dan belum idle"
                    ) from exc
            finally:
                if is_proxy_switch_waiter:
                    async with self._lock:
                        rem_w = max(0, self._proxy_switch_waiters.get(key, 0) - 1)
                        if rem_w == 0:
                            self._proxy_switch_waiters.pop(key, None)
                        else:
                            self._proxy_switch_waiters[key] = rem_w

    async def release(self, auth_token: str, ctx: BrowserContext) -> None:
        key = hashlib.sha256(f"xchat:{auth_token}".encode()).hexdigest()[:16]
        async with self._lock:
            count = self._ctx_use.get(id(ctx), 0)
            if count > 1:
                self._ctx_use[id(ctx)] = count - 1
                return
            self._ctx_use.pop(id(ctx), None)
            dropped = ctx in self._dropped
            if dropped:
                self._dropped.discard(ctx)
            elif self._closing_count.get(key, 0) == 0:
                ev = self._idle_events.pop(key, None)
                if ev is not None:
                    ev.set()
        if dropped:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass
            finally:
                async with self._lock:
                    self._ctx_keys.pop(id(ctx), None)
                    rem = max(0, self._closing_count.get(key, 0) - 1)
                    if rem == 0:
                        self._closing_count.pop(key, None)
                        ev = self._idle_events.pop(key, None)
                        if ev is not None:
                            ev.set()
                    else:
                        self._closing_count[key] = rem

    async def invalidate(self, auth_token: str) -> None:
        key = hashlib.sha256(f"xchat:{auth_token}".encode()).hexdigest()[:16]
        async with self._lock:
            ctx = self._ctxs.pop(key, None)
            self._ctx_proxy.pop(key, None)
            if ctx is None:
                return
            self._ctx_keys[id(ctx)] = key
            if self._ctx_use.get(id(ctx), 0) > 0:
                self._dropped.add(ctx)
                self._closing_count[key] = self._closing_count.get(key, 0) + 1
                return
            self._ctx_use.pop(id(ctx), None)
            self._closing_count[key] = self._closing_count.get(key, 0) + 1
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001
            pass
        finally:
            async with self._lock:
                self._ctx_keys.pop(id(ctx), None)
                rem = max(0, self._closing_count.get(key, 0) - 1)
                if rem == 0:
                    self._closing_count.pop(key, None)
                    ev = self._idle_events.pop(key, None)
                    if ev is not None:
                        ev.set()
                else:
                    self._closing_count[key] = rem

    async def close_all(self) -> None:
        async with self._lock:
            closing_pairs: list[tuple[str, BrowserContext]] = list(self._ctxs.items())
            for d_ctx in self._dropped:
                d_key = self._ctx_keys.get(id(d_ctx), "")
                closing_pairs.append((d_key, d_ctx))
            self._ctxs.clear()
            self._ctx_proxy.clear()
            self._ctx_use.clear()
            self._ctx_keys.clear()
            self._dropped.clear()
            self._closing_count.clear()
            for k, _ in closing_pairs:
                if k:
                    self._closing_count[k] = self._closing_count.get(k, 0) + 1
        try:
            for _, ctx in closing_pairs:
                try:
                    await ctx.close()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            async with self._lock:
                for k, _ in closing_pairs:
                    if not k:
                        continue
                    rem = max(0, self._closing_count.get(k, 0) - 1)
                    if rem == 0:
                        self._closing_count.pop(k, None)
                    else:
                        self._closing_count[k] = rem
                for k in [k for k in list(self._idle_events) if self._closing_count.get(k, 0) == 0]:
                    ev = self._idle_events.pop(k, None)
                    if ev is not None:
                        ev.set()

    def stats(self) -> dict[str, int]:
        return {
            "contexts": len(self._ctxs),
            "max": XCHAT_PERSISTENT_MAX,
            "profile_dir": XCHAT_PROFILE_DIR,
        }


async def click_action_via_browser(
    auth_token: str,
    navigate_url: str,
    click_selector: str,
    confirm_selector: Optional[str] = None,
    match_response_substr: Optional[str | list[str]] = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """
    Lakukan UI action di X (click bookmark/unblock/like button), capture
    response API yang ke-fire akibatnya. Ini pakai TID asli dari client X.

    `match_response_substr` = string/list yang harus ada di URL response untuk di-capture.

    Concurrency: page lifecycle di-batasi `PlaywrightPool.semaphore`.
    Identical concurrent clicks coalesce.
    """
    key = _click_key(auth_token, navigate_url, click_selector, match_response_substr, confirm_selector)
    return await _coalescer.run(key, lambda: _click_coalesced(
        auth_token, navigate_url, click_selector, confirm_selector,
        match_response_substr, timeout,
    ))


async def _click_coalesced(
    auth_token: str,
    navigate_url: str,
    click_selector: str,
    confirm_selector: Optional[str],
    match_response_substr: Optional[str | list[str]],
    timeout: float,
) -> dict[str, Any]:
    async with PlaywrightPool.get().semaphore:
        return await _click_action_via_browser_impl(
            auth_token, navigate_url, click_selector, confirm_selector,
            match_response_substr, timeout,
        )


async def _check_nav_response_error(auth_token: str, nav_resp: Any) -> Optional[dict[str, Any]]:
    """Jika navigasi utama `page.goto()` langsung dibalas HTTP >= 400 oleh proxy/WAF/X,
    evict ContextPool segera tanpa menunggu timeout 20 detik."""
    nav_st = getattr(nav_resp, "status", None) if nav_resp is not None else None
    if not isinstance(nav_st, int) or nav_st < 400:
        return None
    if nav_st == 401:
        from app.response_cache import ResponseCache
        ResponseCache.get().invalidate_token(auth_token)
    if nav_st in (401, 403, 402, 407) or nav_st >= 500:
        await ContextPool.get().invalidate(auth_token, all_proxies=(nav_st == 401))
    return {
        "status": "invalid" if nav_st == 401 else "error",
        "http_status": 502 if nav_st in (402, 407) else nav_st,
        "error": f"browser navigation HTTP {nav_st}",
        "data": None,
    }


async def _click_action_via_browser_impl(
    auth_token: str,
    navigate_url: str,
    click_selector: str,
    confirm_selector: Optional[str] = None,
    match_response_substr: Optional[str | list[str]] = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    context = await ContextPool.get().acquire(auth_token)
    page = None

    captured: dict[str, Any] = {}
    captured_ev = asyncio.Event()
    matchers: list[str] = []
    if match_response_substr:
        matchers = [match_response_substr] if isinstance(match_response_substr, str) else list(match_response_substr)

    async def _on_response(resp: Response) -> None:
        if captured_ev.is_set():
            return
        try:
            req = getattr(resp, "request", None)
            if req is not None and getattr(req, "method", None) == "OPTIONS":
                return
        except Exception:  # noqa: BLE001
            pass
        if matchers and not any(m in resp.url for m in matchers):
            return
        try:
            body_json = await resp.json()
            if not captured_ev.is_set():
                captured["data"] = body_json
                captured["status"] = resp.status
                captured["url"] = resp.url
                captured_ev.set()
        except Exception:  # noqa: BLE001
            try:
                body_txt = (await resp.text())[:1000]
                if not captured_ev.is_set():
                    captured["raw"] = body_txt
                    captured["status"] = resp.status
                    captured["url"] = resp.url
                    captured_ev.set()
            except Exception:  # noqa: BLE001
                pass

    try:
        page = await context.new_page()
        try:
            nav_resp = await page.goto(navigate_url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        except Exception as exc:  # noqa: BLE001
            from app.config import redact_proxy_creds
            await ContextPool.get().invalidate(auth_token, all_proxies=False)
            return {
                "status": "error",
                "http_status": 502,
                "error": redact_proxy_creds(f"browser navigation failed: {type(exc).__name__}: {exc}"),
                "data": None,
            }
        nav_err = await _check_nav_response_error(auth_token, nav_resp)
        if nav_err is not None:
            return nav_err
        await asyncio.sleep(2)
        # Attach listener right before click so navigation HTML responses are
        # never prematurely captured when match_response_substr is omitted.
        page.on("response", lambda r: asyncio.create_task(_on_response(r)))

        try:
            await page.click(click_selector, timeout=int(timeout * 1000 / 2))
        except Exception as e:  # noqa: BLE001
            from app.config import redact_proxy_creds
            return {"status": "error", "http_status": 502, "error": redact_proxy_creds(f"click failed: {e}"), "data": None}

        if confirm_selector:
            await asyncio.sleep(1)
            try:
                await page.click(confirm_selector, timeout=5000)
            except Exception:  # noqa: BLE001
                pass

        try:
            await asyncio.wait_for(captured_ev.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

        if "data" not in captured and "raw" not in captured:
            return {"status": "error", "http_status": 502, "error": "no response captured", "data": None}

        if captured.get("status", 0) >= 400:
            cap_st = int(captured.get("status") or 502)
            if cap_st == 401:
                from app.response_cache import ResponseCache
                ResponseCache.get().invalidate_token(auth_token)
            if cap_st in (401, 403, 402, 407):
                await ContextPool.get().invalidate(auth_token, all_proxies=(cap_st == 401))
            return {
                "status": "invalid" if cap_st == 401 else "error",
                "http_status": 502 if cap_st in (402, 407) else cap_st,
                "error": captured.get("data") or captured.get("raw"),
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": captured.get("status", 200),
            "data": captured.get("data") or {"raw": captured.get("raw")},
        }
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
        await ContextPool.get().release(auth_token, context)
        # context tetap di pool — jangan close


async def action_via_browser(
    auth_token: str,
    url: str,
    method: str = "POST",
    body: Optional[str | dict[str, Any]] = None,
    content_type: str = "application/json",
    timeout: float = 25.0,
) -> dict[str, Any]:
    """
    Eksekusi REST/GraphQL call dari konteks browser asli — anti-bot script X
    otomatis inject `x-client-transaction-id`, jadi endpoint write yang gated
    (CreateBookmark, blocks/destroy, dll) jalan.

    `body` bisa str (raw, biasanya form-urlencoded) atau dict (auto JSON.stringify).
    """
    async with PlaywrightPool.get().semaphore:
        return await _action_via_browser_impl(auth_token, url, method, body, content_type, timeout)


async def _action_via_browser_impl(
    auth_token: str,
    url: str,
    method: str = "POST",
    body: Optional[str | dict[str, Any]] = None,
    content_type: str = "application/json",
    timeout: float = 25.0,
) -> dict[str, Any]:
    from app.config import WEB_BEARER
    context = await ContextPool.get().acquire(auth_token)
    page = None

    try:
        page = await context.new_page()
        # Warm: x.com/home → page jadi punya semua cookie + TID generator loaded
        try:
            nav_resp = await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=int(timeout * 1000))
        except Exception as exc:  # noqa: BLE001
            from app.config import redact_proxy_creds
            await ContextPool.get().invalidate(auth_token, all_proxies=False)
            return {
                "status": "error",
                "http_status": 502,
                "error": redact_proxy_creds(f"browser navigation failed: {type(exc).__name__}: {exc}"),
                "data": None,
            }
        nav_err = await _check_nav_response_error(auth_token, nav_resp)
        if nav_err is not None:
            return nav_err
        # Tunggu sampai bundle ready (TID generator init)
        await asyncio.sleep(3)

        # Build fetch args di-eksekusi di context window (CSRF/TID di-inject otomatis)
        if isinstance(body, dict):
            import json as _json
            body_str = _json.dumps(body)
        else:
            body_str = body or ""

        try:
            result = await page.evaluate(
                """async ({url, method, body, contentType, bearer}) => {
                    const ct0 = (document.cookie.match(/ct0=([^;]+)/) || [])[1] || "";
                    const opts = {
                        method,
                        credentials: "include",
                        headers: {
                            "authorization": "Bearer " + bearer,
                            "content-type": contentType,
                            "x-csrf-token": ct0,
                            "x-twitter-auth-type": "OAuth2Session",
                            "x-twitter-active-user": "yes",
                            "x-twitter-client-language": "en",
                        },
                    };
                    if (method !== "GET" && method !== "HEAD" && body) opts.body = body;
                    const r = await fetch(url, opts);
                    let txt = await r.text();
                    let json = null;
                    try { json = JSON.parse(txt); } catch (e) {}
                    return { status: r.status, body: json !== null ? json : txt };
                }""",
                {"url": url, "method": method, "body": body_str, "contentType": content_type, "bearer": WEB_BEARER},
            )
        except Exception as exc:  # noqa: BLE001
            from app.config import redact_proxy_creds
            await ContextPool.get().invalidate(auth_token, all_proxies=False)
            return {
                "status": "error",
                "http_status": 502,
                "error": redact_proxy_creds(f"browser fetch failed: {type(exc).__name__}: {exc}"),
                "data": None,
            }

        cookies = await context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        status_code = result.get("status", 0)
        payload = result.get("body")

        if status_code >= 400:
            if status_code == 401:
                from app.response_cache import ResponseCache
                ResponseCache.get().invalidate_token(auth_token)
            if status_code in (401, 403, 402, 407):
                await ContextPool.get().invalidate(auth_token, all_proxies=(status_code == 401))
            return {
                "status": "invalid" if status_code == 401 else "error",
                "http_status": 502 if status_code in (402, 407) else status_code,
                "error": payload,
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": status_code,
            "data": payload,
        }
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
        await ContextPool.get().release(auth_token, context)
        # context tetap di pool — jangan close


async def fetch_via_browser(
    auth_token: str,
    navigate_url: str,
    match_path: str | list[str],
    timeout: float = 20.0,
    click_selector: Optional[str] = None,
) -> dict[str, Any]:
    """
    Generic: buka `navigate_url` di browser, intercept response yang URL-nya mengandung
    salah satu dari `match_path` (str atau list[str]), return raw JSON dari yang ke-capture pertama.

    Kalau `click_selector` di-pass, akan di-click setelah page load (untuk trigger tab
    yang nggak auto-fire request, mis. tab Replies).

    Pakai untuk endpoint GraphQL yang di-gate Cloudflare (UserByRestId, dll).

    Identical concurrent fetches coalesce — share one page load.
    """
    key = _fetch_key(auth_token, navigate_url, match_path, click_selector)
    return await _coalescer.run(key, lambda: _fetch_coalesced(auth_token, navigate_url, match_path, timeout, click_selector))


async def _fetch_coalesced(
    auth_token: str,
    navigate_url: str,
    match_path: str | list[str],
    timeout: float,
    click_selector: Optional[str],
) -> dict[str, Any]:
    async with PlaywrightPool.get().semaphore:
        return await _fetch_via_browser_impl(auth_token, navigate_url, match_path, timeout, click_selector)


async def _fetch_via_browser_impl(
    auth_token: str,
    navigate_url: str,
    match_path: str | list[str],
    timeout: float = 20.0,
    click_selector: Optional[str] = None,
) -> dict[str, Any]:
    context = await ContextPool.get().acquire(auth_token)
    page = None

    captured: dict[str, Any] = {}
    matchers = [match_path] if isinstance(match_path, str) else list(match_path)

    async def _on_response(resp: Response) -> None:
        if "data" in captured or "raw" in captured:
            return
        try:
            req = getattr(resp, "request", None)
            if req is not None and getattr(req, "method", None) == "OPTIONS":
                return
        except Exception:  # noqa: BLE001
            pass
        if not any(m in resp.url for m in matchers):
            return
        try:
            body_json = await resp.json()
            if "data" not in captured and "raw" not in captured:
                captured["data"] = body_json
                captured["url"] = resp.url
                captured["status"] = resp.status
        except Exception:  # noqa: BLE001
            try:
                body_txt = (await resp.text())[:2000]
                if "data" not in captured and "raw" not in captured:
                    captured["raw"] = body_txt
                    captured["url"] = resp.url
                    captured["status"] = resp.status
            except Exception:  # noqa: BLE001
                pass

    try:
        page = await context.new_page()
        page.on("response", lambda r: asyncio.create_task(_on_response(r)))
        try:
            nav_resp = await page.goto(navigate_url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        except Exception as exc:  # noqa: BLE001
            from app.config import redact_proxy_creds
            await ContextPool.get().invalidate(auth_token, all_proxies=False)
            return {
                "status": "error",
                "http_status": 502,
                "error": redact_proxy_creds(f"browser navigation failed: {type(exc).__name__}: {exc}"),
                "data": None,
            }
        nav_err = await _check_nav_response_error(auth_token, nav_resp)
        if nav_err is not None and "data" not in captured and "raw" not in captured:
            return nav_err

        if click_selector:
            try:
                await page.click(click_selector, timeout=int(timeout * 1000))
            except Exception:  # noqa: BLE001
                pass

        deadline = asyncio.get_event_loop().time() + timeout
        while "data" not in captured and "raw" not in captured and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.2)

        if "data" not in captured:
            raw_st = captured.get("status")
            if raw_st == 401:
                from app.response_cache import ResponseCache
                ResponseCache.get().invalidate_token(auth_token)
            if isinstance(raw_st, int) and raw_st in (401, 403, 402, 407):
                await ContextPool.get().invalidate(auth_token, all_proxies=(raw_st == 401))
            norm_raw_st = (
                502
                if (not isinstance(raw_st, int) or raw_st < 400 or raw_st in (402, 407))
                else raw_st
            )
            err_msg = (
                f"upstream non-JSON response ({raw_st})"
                if "raw" in captured
                else f"timeout: response {match_path} tidak ter-capture"
            )
            return {
                "status": "invalid" if raw_st == 401 else "error",
                "error": err_msg,
                "captured_url": captured.get("url"),
                "http_status": norm_raw_st,
                "raw": captured.get("raw"),
                "data": None,
            }

        if captured.get("status", 0) >= 400:
            cap_st = int(captured.get("status") or 502)
            if cap_st == 401:
                from app.response_cache import ResponseCache
                ResponseCache.get().invalidate_token(auth_token)
            if cap_st in (401, 403, 402, 407):
                await ContextPool.get().invalidate(auth_token, all_proxies=(cap_st == 401))
            return {
                "status": "invalid" if cap_st == 401 else "error",
                "http_status": 502 if cap_st in (402, 407) else cap_st,
                "captured_url": captured.get("url"),
                "error": captured.get("data") or captured.get("raw"),
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": captured.get("status", 200),
            "captured_url": captured.get("url"),
            "data": captured["data"],
        }
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
        await ContextPool.get().release(auth_token, context)
        # context tetap di pool — jangan close


async def search_via_browser(
    auth_token: str,
    q: str,
    search_type: SearchType = "Latest",
    timeout: float = 20.0,
) -> dict[str, Any]:
    """
    Buka x.com/search, tangkap response SearchTimeline / adaptive.json.
    Return: {status, data: <raw GraphQL JSON>, cookies, captured_url}

    Identical concurrent searches coalesce — share one page load.
    """
    key = _search_key(auth_token, q, search_type)
    return await _coalescer.run(key, lambda: _search_coalesced(auth_token, q, search_type, timeout))


async def _search_coalesced(
    auth_token: str,
    q: str,
    search_type: SearchType,
    timeout: float,
) -> dict[str, Any]:
    async with PlaywrightPool.get().semaphore:
        return await _search_via_browser_impl(auth_token, q, search_type, timeout)


async def _search_via_browser_impl(
    auth_token: str,
    q: str,
    search_type: SearchType = "Latest",
    timeout: float = 20.0,
) -> dict[str, Any]:
    context = await ContextPool.get().acquire(auth_token)
    page = None

    captured: dict[str, Any] = {}

    def _is_search_response(resp: Response) -> bool:
        url = resp.url
        return (
            "/i/api/graphql/" in url and "/SearchTimeline" in url
        ) or "/i/api/2/search/adaptive.json" in url

    async def _on_response(resp: Response) -> None:
        if "data" in captured or "raw" in captured:
            return
        try:
            req = getattr(resp, "request", None)
            if req is not None and getattr(req, "method", None) == "OPTIONS":
                return
        except Exception:  # noqa: BLE001
            pass
        if not _is_search_response(resp):
            return
        try:
            body = await resp.json()
            if "data" not in captured and "raw" not in captured:
                captured["data"] = body
                captured["url"] = resp.url
                captured["status"] = resp.status
        except Exception:  # noqa: BLE001
            try:
                body_txt = (await resp.text())[:2000]
                if "data" not in captured and "raw" not in captured:
                    captured["raw"] = body_txt
                    captured["url"] = resp.url
                    captured["status"] = resp.status
            except Exception:  # noqa: BLE001
                pass

    try:
        page = await context.new_page()
        page.on("response", lambda r: asyncio.create_task(_on_response(r)))
        f = URL_FILTER.get(search_type, "live")
        from urllib.parse import quote

        url = f"https://x.com/search?q={quote(q)}&src=typed_query&f={f}"
        try:
            nav_resp = await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        except Exception as exc:  # noqa: BLE001
            from app.config import redact_proxy_creds
            await ContextPool.get().invalidate(auth_token, all_proxies=False)
            return {
                "status": "error",
                "http_status": 502,
                "error": redact_proxy_creds(f"browser navigation failed: {type(exc).__name__}: {exc}"),
                "data": None,
            }
        nav_err = await _check_nav_response_error(auth_token, nav_resp)
        if nav_err is not None and "data" not in captured and "raw" not in captured:
            return nav_err

        # Tunggu response ke-capture
        deadline = asyncio.get_event_loop().time() + timeout
        while "data" not in captured and "raw" not in captured and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.2)

        if "data" not in captured:
            raw_st = captured.get("status")
            if raw_st == 401:
                from app.response_cache import ResponseCache
                ResponseCache.get().invalidate_token(auth_token)
            if isinstance(raw_st, int) and raw_st in (401, 403, 402, 407):
                await ContextPool.get().invalidate(auth_token, all_proxies=(raw_st == 401))
            norm_raw_st = (
                502
                if (not isinstance(raw_st, int) or raw_st < 400 or raw_st in (402, 407))
                else raw_st
            )
            err_msg = (
                f"upstream non-JSON response ({raw_st})"
                if "raw" in captured
                else "timeout: response SearchTimeline/adaptive.json tidak ter-capture"
            )
            return {
                "status": "invalid" if raw_st == 401 else "error",
                "error": err_msg,
                "captured_url": captured.get("url"),
                "http_status": norm_raw_st,
                "raw": captured.get("raw"),
                "data": None,
            }

        if captured.get("status", 0) >= 400:
            cap_st = int(captured.get("status") or 502)
            if cap_st == 401:
                from app.response_cache import ResponseCache
                ResponseCache.get().invalidate_token(auth_token)
            if cap_st in (401, 403, 402, 407):
                await ContextPool.get().invalidate(auth_token, all_proxies=(cap_st == 401))
            return {
                "status": "invalid" if cap_st == 401 else "error",
                "http_status": 502 if cap_st in (402, 407) else cap_st,
                "captured_url": captured.get("url"),
                "error": captured.get("data") or captured.get("raw"),
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": captured.get("status", 200),
            "captured_url": captured.get("url"),
            "data": captured["data"],
        }
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass
        await ContextPool.get().release(auth_token, context)
        # context tetap di pool — jangan close
