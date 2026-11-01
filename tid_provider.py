"""
x-client-transaction-id (TID) generator wrapper.

X anti-bot gate write endpoints (CreateTweet, CreateBookmark, blocks/destroy)
dengan header `x-client-transaction-id` yang di-generate sisi browser.
Library `xclienttransaction` port algoritmanya. Kita wrap + cache home_page +
ondemand_file (refresh tiap 1 jam) supaya generate TID hanya butuh HMAC lokal.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Optional

import bs4
import requests
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import handle_x_migration, get_ondemand_file_url

log = logging.getLogger(__name__)

# Refresh tiap 1 jam — ondemand JS jarang berubah.
TTL_SECONDS = 3600

# Max consecutive refresh failures before fallback mode.
# Fallback TIDs are UUID-based — still accepted by X but less stealthy.
MAX_REFRESH_FAILURES = 3

# Saat fallback mode, jangan coba refresh tiap request — ulangi tiap 5 menit.
FALLBACK_REFRESH_BACKOFF = 300


class TIDProvider:
    """Singleton ClientTransaction holder. Refresh setiap TTL_SECONDS."""

    _instance: Optional["TIDProvider"] = None

    def __init__(self) -> None:
        self._ct: Optional[ClientTransaction] = None
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()
        self._refresh_failures: int = 0
        self._fallback_mode: bool = False
        self._next_refresh_try: float = 0.0

    @classmethod
    def get(cls) -> "TIDProvider":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _is_stale(self) -> bool:
        return self._ct is None or (time.time() - self._loaded_at) > TTL_SECONDS

    async def _refresh(self, auth_token: Optional[str] = None) -> None:
        loop = asyncio.get_event_loop()

        def _fetch_home_via_requests() -> str:
            sess = requests.Session()
            sess.timeout = (5, 10)  # connect=5s, read=10s
            sess.headers["User-Agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
            return str(handle_x_migration(sess))

        async def _fetch_home_via_client() -> Optional[str]:
            """Home login via curl_cffi impersonate — tanpa browser.

            HTML shell versi login (SVG `loading-x-anim` + chunk-map
            `ondemand.s` utuh) itulah yang dibutuhkan ClientTransaction.
            Home logged-out via requests biasa sudah tidak memuat chunk-map
            (X mengubah landing page), sedangkan jalur browser butuh Chromium.
            Session pool sudah ber-cookie auth_token + impersonate Chrome +
            proxy per token — cukup 1 HTTP request.
            """
            if not auth_token:
                return None
            try:
                from app.client_pool import pooled_client

                async with pooled_client(auth_token) as client:
                    resp = await client.get(
                        "https://x.com/home",
                        headers={"Referer": "https://x.com/"},
                    )
                    if resp.status_code != 200:
                        log.warning(
                            "TID home fetch via client: HTTP %s",
                            resp.status_code,
                        )
                        return None
                    return resp.text
            except Exception as e:  # noqa: BLE001
                log.warning("TID home fetch via client failed: %s", e)
                return None

        async def _fetch_home_via_browser() -> Optional[str]:
            # Jalur browser hanya saat PLAYWRIGHT_ENABLED=1 — di VPS tanpa
            # binary Chromium jalur ini selalu gagal, dan sebelumnya gagalnya
            # "diam-diam" (refresh tetap sukses via requests) sehingga dicoba
            # ulang terus: satu driver node 130MB bocor per percobaan.
            if not auth_token:
                return None
            try:
                from playwright_search import PLAYWRIGHT_ENABLED
                if not PLAYWRIGHT_ENABLED:
                    return None
            except Exception:  # noqa: BLE001
                return None
            try:
                from playwright_search import ContextPool

                ctx = await ContextPool.get().acquire(auth_token)
                page = await ctx.new_page()
                try:
                    # Raw response body — bukan page.content(): X menghapus
                    # SVG `loading-x-anim` (animation key frames) dari DOM
                    # setelah app mount, jadi DOM-nya tidak bisa dipakai
                    # untuk generate animation key.
                    resp = await page.goto(
                        "https://x.com/home",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    if resp is None:
                        return None
                    return await resp.text()
                finally:
                    await page.close()
            except Exception as e:  # noqa: BLE001
                log.warning("TID home fetch via browser failed: %s", e)
                return None

        # Urutan: browser (jika PLAYWRIGHT_ENABLED=1) → curl_cffi login →
        # requests logged-out (sering tak memuat chunk-map lagi).
        home_html = (
            await _fetch_home_via_browser()
            or await _fetch_home_via_client()
            or await loop.run_in_executor(None, _fetch_home_via_requests)
        )
        home = bs4.BeautifulSoup(home_html, "html.parser")

        def _do() -> ClientTransaction:
            sess = requests.Session()
            sess.timeout = (5, 10)
            sess.headers["User-Agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
            ondemand_url = get_ondemand_file_url(response=home)
            ondemand_resp = sess.get(ondemand_url, timeout=10)
            ondemand = bs4.BeautifulSoup(ondemand_resp.content, "html.parser")
            return ClientTransaction(home, ondemand)

        self._ct = await loop.run_in_executor(None, _do)
        self._loaded_at = time.time()

    async def generate(self, method: str, path: str, auth_token: Optional[str] = None) -> str:
        """
        method = "GET" / "POST" / "DELETE".
        path = "/i/api/graphql/abc/CreateTweet" atau "/1.1/blocks/destroy.json".

        Graceful fallback: if xclienttransaction refresh fails 3 consecutive
        times, fall back to UUID-based TIDs. X still accepts these — just
        slightly less stealthy than algorithmically correct TIDs. The
        fallback lets write endpoints survive library breakage.
        """
        async with self._lock:
            if self._is_stale() and time.time() >= self._next_refresh_try:
                try:
                    await self._refresh(auth_token)
                    self._refresh_failures = 0
                    self._fallback_mode = False
                except Exception as e:  # noqa: BLE001
                    self._refresh_failures += 1
                    log.warning(
                        "TID refresh failed (%d/%d): %s",
                        self._refresh_failures, MAX_REFRESH_FAILURES, e,
                    )
                    if self._refresh_failures >= MAX_REFRESH_FAILURES:
                        self._fallback_mode = True
                        # Backoff: jangan coba refresh tiap request — tiap
                        # percobaan = fetch home + ondemand ke x.com.
                        self._next_refresh_try = (
                            time.time() + FALLBACK_REFRESH_BACKOFF
                        )
                        log.error(
                            "TIDProvider entering fallback mode — "
                            "UUID-based TIDs will be used. Retry refresh "
                            "in %ds. Write endpoints will still work but "
                            "may be slightly less stealthy.",
                            FALLBACK_REFRESH_BACKOFF,
                        )
            ct = self._ct

        if self._fallback_mode or ct is None:
            return self._fallback_tid(method, path)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: ct.generate_transaction_id(method=method, path=path)
        )

    def _fallback_tid(self, method: str, path: str) -> str:
        """UUID-based TID when xclienttransaction is unavailable.

        Format: fallback-{uuid}
        X does NOT reject non-standard TID formats — the header is
        primarily a telemetry/anti-bot signal, not a strict validation gate.
        """
        return f"fallback-{uuid.uuid4().hex}"

    async def stats(self) -> dict:
        return {
            "loaded": self._ct is not None,
            "age_seconds": int(time.time() - self._loaded_at) if self._ct else None,
            "ttl_seconds": TTL_SECONDS,
            "refresh_failures": self._refresh_failures,
            "fallback_mode": self._fallback_mode,
        }
