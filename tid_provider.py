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


class TIDProvider:
    """Singleton ClientTransaction holder. Refresh setiap TTL_SECONDS."""

    _instance: Optional["TIDProvider"] = None

    def __init__(self) -> None:
        self._ct: Optional[ClientTransaction] = None
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()
        self._refresh_failures: int = 0
        self._fallback_mode: bool = False

    @classmethod
    def get(cls) -> "TIDProvider":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _is_stale(self) -> bool:
        return self._ct is None or (time.time() - self._loaded_at) > TTL_SECONDS

    async def _refresh(self) -> None:
        loop = asyncio.get_event_loop()

        def _do() -> ClientTransaction:
            sess = requests.Session()
            sess.timeout = (5, 10)  # connect=5s, read=10s
            sess.headers["User-Agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
            home = handle_x_migration(sess)
            ondemand_url = get_ondemand_file_url(response=home)
            ondemand_resp = sess.get(ondemand_url, timeout=10)
            ondemand = bs4.BeautifulSoup(ondemand_resp.content, "html.parser")
            return ClientTransaction(home, ondemand)

        self._ct = await loop.run_in_executor(None, _do)
        self._loaded_at = time.time()

    async def generate(self, method: str, path: str) -> str:
        """
        method = "GET" / "POST" / "DELETE".
        path = "/i/api/graphql/abc/CreateTweet" atau "/1.1/blocks/destroy.json".

        Graceful fallback: if xclienttransaction refresh fails 3 consecutive
        times, fall back to UUID-based TIDs. X still accepts these — just
        slightly less stealthy than algorithmically correct TIDs. The
        fallback lets write endpoints survive library breakage.
        """
        async with self._lock:
            if self._is_stale():
                try:
                    await self._refresh()
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
                        log.error(
                            "TIDProvider entering fallback mode — "
                            "UUID-based TIDs will be used. Write endpoints "
                            "will still work but may be slightly less stealthy."
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
