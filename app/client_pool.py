"""HTTP client pool: reuse AsyncSession per auth_token to amortize TLS handshake cost.

Key insight: each `make_client(token)` call creates a fresh AsyncSession with a
TLS handshake (impersonate=chrome124, ~50-150ms). Reusing the session across
requests for the same `auth_token` cuts that cost to zero. We bound the pool
to `CLIENT_POOL_MAX` to avoid memory blow-up, and expire idle sessions after
`CLIENT_POOL_TTL` so cookie jars don't go stale.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from curl_cffi.requests import AsyncSession

from .config import (
    CLIENT_POOL_MAX,
    CLIENT_POOL_TTL,
    gen_ct0,
    headers_for_token,
    profile_for_token,
    proxy_for_token,
    token_key,
)


class _Entry:
    __slots__ = ("session", "last_used", "lock", "in_use", "dropped")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.last_used: float = time.time()
        self.lock = asyncio.Lock()
        # Jumlah coroutine yang memegang session ini via pooled_client().
        # Di-increment DI DALAM acquire() (di bawah pool lock) supaya eviction
        # / TTL-sweep tidak pernah menutup session di antara acquire() dan
        # request pertama. Di-decrement di release().
        self.in_use: int = 0
        # True kalau entry dihapus dari pool saat masih dipakai
        # (invalidate / eviction race) — holder terakhir yang menutup.
        self.dropped: bool = False

    async def close(self) -> None:
        try:
            await self.session.close()
        except Exception:  # noqa: BLE001
            pass


class ClientPool:
    """LRU pool of AsyncSession keyed by auth_token.

    Sessions are reused across requests to skip cold TLS handshake. When the
    pool exceeds `CLIENT_POOL_MAX`, the least-recently-used IDLE entry is
    evicted and its session closed — entries yang masih in-use tidak pernah
    ditutup (pool boleh melebihi max sementara).
    """

    _instance: "ClientPool | None" = None

    def __init__(self) -> None:
        self._cache: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> "ClientPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def acquire(self, auth_token: str) -> tuple[AsyncSession, _Entry]:
        """Get or create a pooled session.

        Returns:
            (session, entry) — caller harus memegang `entry.lock` selama
            request (hindari race cookie jar) dan memanggil
            `release(entry)` setelah selesai. `entry.in_use` sudah
            di-increment di sini di bawah pool lock.
        """
        key = token_key(auth_token)
        async with self._lock:
            now = time.time()
            # Expire stale entries first (skip entries currently in use)
            stale = [k for k, e in self._cache.items() if e.in_use == 0 and (now - e.last_used) > CLIENT_POOL_TTL]
            for k in stale:
                old = self._cache.pop(k)
                await old.close()

            entry = self._cache.get(key)
            if entry:
                self._cache.move_to_end(key)
                entry.last_used = now
            else:
                # Build new session with deterministic browser profile (TLS + UA + sec-ch-ua) + proxy
                prof = profile_for_token(auth_token)
                headers = headers_for_token(auth_token)
                proxy = proxy_for_token(auth_token)
                kwargs: dict[str, Any] = dict(
                    cookies={"auth_token": auth_token, "ct0": gen_ct0()},
                    headers=headers,
                    timeout=20.0,
                    impersonate=prof["impersonate"],
                    allow_redirects=True,
                )
                if proxy:
                    kwargs["proxies"] = {"http": proxy, "https": proxy}
                entry = _Entry(AsyncSession(**kwargs))
                self._cache[key] = entry

            # Tandai in-use SEBELUM pool lock dilepas — eviction/TTL-sweep
            # berjalan di bawah lock yang sama, jadi tidak ada window di mana
            # session bisa ditutup di antara acquire() dan request pertama.
            entry.in_use += 1

            # Evict LRU if over capacity (skip entries currently in use)
            while len(self._cache) > CLIENT_POOL_MAX:
                # Find the least-recently-used entry that is NOT in use
                evict_key = None
                for k, e in self._cache.items():
                    if e.in_use == 0:
                        evict_key = k
                        break
                if evict_key is None:
                    break  # all entries are in use, cannot evict
                lru_entry = self._cache.pop(evict_key)
                await lru_entry.close()

            return entry.session, entry

    async def release(self, entry: _Entry) -> None:
        """Lepas entry hasil acquire(); tutup session kalau entry di-drop
        dari pool saat masih dipakai (invalidate) dan ini holder terakhir."""
        async with self._lock:
            entry.in_use = max(0, entry.in_use - 1)
            should_close = entry.dropped and entry.in_use == 0
        if should_close:
            await entry.close()

    async def invalidate(self, auth_token: str) -> None:
        """Drop session (e.g., on 401/403) so next request gets fresh TLS.

        If the session is currently in use, it is removed from the pool (so no
        new caller can acquire it) and close() is deferred to release().
        """
        key = token_key(auth_token)
        async with self._lock:
            entry = self._cache.pop(key, None)
            if entry and entry.in_use > 0:
                entry.dropped = True  # holder terakhir menutup via release()
                entry = None
        if entry:
            await entry.close()

    async def close_all(self) -> None:
        """Shutdown hook."""
        async with self._lock:
            entries = list(self._cache.values())
            self._cache.clear()
        for e in entries:
            try:
                await e.session.close()
            except Exception:  # noqa: BLE001
                pass

    async def stats(self) -> dict[str, int]:
        async with self._lock:
            return {
                "size": len(self._cache),
                "max": CLIENT_POOL_MAX,
                "ttl_seconds": CLIENT_POOL_TTL,
            }


@asynccontextmanager
async def pooled_client(auth_token: str) -> AsyncIterator[AsyncSession]:
    """Async context manager: acquire pooled session, yield with lock held.

    Usage:
        async with pooled_client(auth_token) as client:
            resp = await client.get(...)

    Lock prevents two concurrent requests on the same token from racing on
    the shared cookie jar. (Same-token concurrency is rare in practice — one
    user = one request flow — so contention is low.)

    The in_use counter prevents eviction/TTL-sweep from closing a session
    that is still mid-flight.
    """
    pool = ClientPool.get()
    session, entry = await pool.acquire(auth_token)
    try:
        async with entry.lock:
            yield session
    finally:
        await pool.release(entry)

