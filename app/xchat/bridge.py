"""XChat browser-bridge — keep a real Chromium tab logged in to X with the
bot's auth_token, so the X frontend handles XChat E2E decryption for us.

The browser stores all decrypted plaintext in OPFS at
`backups/chat_{userId}.db` (SQLite). We read that file out on demand and
expose plaintext rows via :mod:`app.xchat.events`.

Why a *persistent* context (vs re-using the existing ContextPool):
- OPFS is scoped to (origin, profile dir). Closing the context drops the
  storage; XChat would have to re-derive keys + re-fetch every time.
- We only need ONE long-lived context per bot account, not per request.

Concurrency: a single asyncio.Lock guards page navigation. chat.db reads
are serialised behind it because the same page evaluates JS to grab the
file. Parallel readers would race the eval handle.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    BrowserContext,
    Page,
    async_playwright,
)

log = logging.getLogger(__name__)


class XChatAuthError(RuntimeError):
    """Bridge could not stay logged in — auth_token was rejected by X.

    Raised when the bot's session ends up at /login or /logout after a goto.
    Caller (e.g. /2/dm_events) should surface this as 401 so the worker
    can mark the account unhealthy instead of silently returning 0 events.
    """

# Where to put the persistent Chromium profile. One dir per bot account so
# OPFS chat.db survives between Xapi restarts.
XCHAT_PROFILE_ROOT = Path(
    os.environ.get("XCHAT_PROFILE_ROOT", "/tmp/xapi-xchat-profiles")
)

# Default landing URL — keep page parked here so XChat client stays warm.
XCHAT_LANDING_URL = "https://x.com/messages"

# 4-digit XChat passcode lookup. Required only on first boot of a fresh
# profile — afterwards the Juicebox-derived keys persist in the profile dir's
# OPFS so subsequent ensure() calls skip the PIN screen automatically.
#
# Resolution order (first hit wins):
#   1. ``XCHAT_PIN_<user_id>``  — preferred, supports multi-bot deploys
#   2. ``XCHAT_PIN``            — single-account fallback
def resolve_xchat_pin(user_id: str) -> str:
    return (
        os.environ.get(f"XCHAT_PIN_{user_id}", "").strip()
        or os.environ.get("XCHAT_PIN", "").strip()
    )


@dataclass
class XChatBridge:
    """One persistent Chromium context per bot account."""

    auth_token: str
    user_id: str  # bot's numeric ID — used for OPFS db filename
    _pw: object | None = None
    _ctx: Optional[BrowserContext] = None
    _page: Optional[Page] = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_warm: float = 0.0

    @property
    def profile_dir(self) -> Path:
        # Sanitise — auth_token is hex/alphanum but be defensive
        safe = "".join(c for c in self.auth_token[:32] if c.isalnum())
        return XCHAT_PROFILE_ROOT / safe

    @staticmethod
    def _is_login_page(url: str) -> bool:
        """Detect X's logged-out redirects.

        X bounces invalid sessions to /login or /i/flow/login (sometimes via
        /logout). All carry a clear path prefix — substring match is enough.
        """
        if not url:
            return False
        return any(p in url for p in ("/login", "/i/flow/login", "/logout"))

    async def ensure(self) -> Page:
        """Spawn the browser + tab if not already running. Idempotent."""
        async with self._lock:
            if self._page is not None and not self._page.is_closed():
                return self._page

            self.profile_dir.mkdir(parents=True, exist_ok=True)
            log.info(
                "xchat-bridge starting profile=%s user=%s", self.profile_dir, self.user_id
            )

            self._pw = await async_playwright().start()
            self._ctx = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/148.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )

            await self._ctx.add_cookies(
                [
                    {
                        "name": "auth_token",
                        "value": self.auth_token,
                        "domain": ".x.com",
                        "path": "/",
                        "httpOnly": True,
                        "secure": True,
                        "sameSite": "None",
                    }
                ]
            )

            self._page = await self._ctx.new_page()
            await self._page.goto(XCHAT_LANDING_URL, wait_until="domcontentloaded", timeout=30_000)
            if self._is_login_page(self._page.url):
                log.warning(
                    "xchat-bridge auth_token rejected user=%s redirected to %s",
                    self.user_id, self._page.url,
                )
                raise XChatAuthError(f"auth_token invalid, redirected to {self._page.url}")
            # Give XChat client time to register, pull initial inbox, and
            # finish the OPFS handshake (GenerateXChatToken + first
            # GetInitialXChatPageQuery + DB write). 12s is empirically the
            # floor on a warm profile; first-ever boot may need more.
            await asyncio.sleep(12)
            await self._maybe_enter_pin()
            # After PIN unlock the XChat client needs time to subscribe + flush
            # its first chat.db snapshot. If we return too early read_chat_db
            # will hit NotFoundError. Park on /messages to nudge inbox sync.
            try:
                await self._page.goto(
                    XCHAT_LANDING_URL,
                    wait_until="domcontentloaded",
                    timeout=20_000,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("xchat-bridge post-PIN landing nav failed: %s", e)
            got_db = await self._wait_chat_db()
            if not got_db:
                log.warning(
                    "xchat-bridge chat.db not materialised after unlock user=%s "
                    "(client may still be syncing — first read will likely miss)",
                    self.user_id,
                )
            self._last_warm = time.time()
            return self._page

    async def _maybe_enter_pin(self) -> None:
        """If parked on /i/chat/pin/recovery, fill XCHAT_PIN and wait for unlock.

        After Juicebox completes, X redirects back to /messages and writes
        backups/chat_{user}.db to OPFS. Skipped silently if no PIN configured
        or if not on the recovery page.
        """
        if self._page is None:
            return
        if "/i/chat/pin/recovery" not in self._page.url:
            return
        pin = resolve_xchat_pin(self.user_id)
        if not pin:
            log.warning(
                "xchat-bridge stuck on PIN recovery user=%s but no XCHAT_PIN_%s "
                "or XCHAT_PIN env set — chat.db will stay empty",
                self.user_id, self.user_id,
            )
            return
        log.info("xchat-bridge entering PIN on recovery page user=%s", self.user_id)
        try:
            await self._page.keyboard.type(pin, delay=120)
            # Wait until redirected off the recovery page (Juicebox takes ~3-6s).
            for _ in range(20):
                await asyncio.sleep(1)
                if "/i/chat/pin/recovery" not in self._page.url:
                    break
            # Give OPFS write a moment to land.
            await asyncio.sleep(4)
        except Exception as e:  # noqa: BLE001
            log.warning("xchat-bridge PIN entry failed: %s", e)

    async def _wait_chat_db(self, max_seconds: int = 90) -> bool:
        """Poll OPFS until `backups/chat_{userId}.db` has real inbox data.

        After PIN unlock the file appears almost immediately at ~500KB with
        only key material — dm_entry/dm_conversation are still empty. The
        XChat client needs another 30-60s to subscribe and flush the inbox
        snapshot. We probe the file size as a cheap proxy for "inbox synced":
        a real inbox is consistently >900KB, key-only files plateau at ~500KB.
        """
        if self._page is None:
            return False
        last_size = 0
        plateau = 0
        for _ in range(max_seconds // 2):
            try:
                size = await self._page.evaluate(
                    """
                    async (userId) => {
                      try {
                        const root = await navigator.storage.getDirectory();
                        const backups = await root.getDirectoryHandle('backups', { create: false });
                        const fh = await backups.getFileHandle('chat_' + userId + '.db', { create: false });
                        const f = await fh.getFile();
                        return f.size;
                      } catch (e) { return 0; }
                    }
                    """,
                    self.user_id,
                )
            except Exception:  # noqa: BLE001
                size = 0
            if size > 900_000:
                return True
            if size > 0 and size == last_size:
                plateau += 1
                if plateau >= 4:  # 8s of no growth — accept whatever we have
                    return size > 0
            else:
                plateau = 0
            last_size = size
            await asyncio.sleep(2)
        return last_size > 0

    async def warm(self) -> None:
        """Re-navigate landing page if it has gone stale (>2 min idle)."""
        async with self._lock:
            if self._page is None or self._page.is_closed():
                return  # ensure() will rebuild
            if time.time() - self._last_warm < 120:
                return
            try:
                await self._page.goto(
                    XCHAT_LANDING_URL,
                    wait_until="domcontentloaded",
                    timeout=20_000,
                )
                await asyncio.sleep(2)
                self._last_warm = time.time()
            except Exception as e:  # noqa: BLE001
                log.warning("xchat-bridge warm failed: %s", e)

    async def read_chat_db(self) -> Optional[bytes]:
        """Read backups/chat_{userId}.db from OPFS via JS bridge.

        Returns the raw SQLite bytes, or None if the file isn't present yet
        (e.g. on a brand-new profile that hasn't completed XChat handshake).
        """
        page = await self.ensure()
        async with self._lock:
            try:
                result = await page.evaluate(
                    """
                    async (userId) => {
                      const out = { ok: false, b64: null, error: null, listing: [] };
                      try {
                        const root = await navigator.storage.getDirectory();
                        async function walk(dir, prefix) {
                          for await (const [name, handle] of dir.entries()) {
                            if (handle.kind === 'directory') {
                              out.listing.push(prefix + name + '/');
                              try { await walk(handle, prefix + name + '/'); }
                              catch (e) { out.listing.push(prefix + name + '/<walk-err>'); }
                            } else {
                              try {
                                const f = await handle.getFile();
                                out.listing.push(prefix + name + ' (' + f.size + 'b)');
                              } catch (e) {
                                out.listing.push(prefix + name + ' <stat-err>');
                              }
                            }
                          }
                        }
                        try { await walk(root, ''); } catch (e) { /* ignore */ }

                        const backups = await root.getDirectoryHandle('backups', { create: false });
                        const fh = await backups.getFileHandle('chat_' + userId + '.db', { create: false });
                        const f = await fh.getFile();
                        const buf = await f.arrayBuffer();
                        const u8 = new Uint8Array(buf);
                        let s = '';
                        const CHUNK = 0x8000;
                        for (let i = 0; i < u8.length; i += CHUNK) {
                          s += String.fromCharCode.apply(null, u8.subarray(i, i + CHUNK));
                        }
                        out.ok = true;
                        out.b64 = btoa(s);
                      } catch (e) {
                        out.error = String(e);
                      }
                      return out;
                    }
                    """,
                    self.user_id,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("xchat-bridge read_chat_db eval failed: %s", e)
                return None

        if not result or not result.get("ok"):
            log.warning(
                "xchat-bridge read_chat_db: file missing user=%s error=%s "
                "opfs_listing=%s",
                self.user_id,
                result.get("error") if result else "<no-result>",
                (result or {}).get("listing", []),
            )
            return None
        import base64
        return base64.b64decode(result["b64"])

    async def close(self) -> None:
        async with self._lock:
            try:
                if self._ctx is not None:
                    await self._ctx.close()
            except Exception:  # noqa: BLE001
                pass
            self._ctx = None
            self._page = None
            try:
                if self._pw is not None:
                    await self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None


class XChatBridgeRegistry:
    """One :class:`XChatBridge` per (auth_token, user_id) tuple."""

    _instance: Optional["XChatBridgeRegistry"] = None

    def __init__(self) -> None:
        self._bridges: dict[str, XChatBridge] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> "XChatBridgeRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def acquire(self, auth_token: str, user_id: str) -> XChatBridge:
        key = f"{auth_token[:16]}:{user_id}"
        async with self._lock:
            br = self._bridges.get(key)
            if br is None:
                br = XChatBridge(auth_token=auth_token, user_id=user_id)
                self._bridges[key] = br
            return br

    async def close_all(self) -> None:
        async with self._lock:
            for br in list(self._bridges.values()):
                await br.close()
            self._bridges.clear()
