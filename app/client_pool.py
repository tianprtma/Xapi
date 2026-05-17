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
    DEFAULT_HEADERS,
    gen_ct0,
    random_proxy,
    random_user_agent,
)


class _Entry:
    __slots__ = ("session", "last_used", "lock")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.last_used: float = time.time()
        self.lock = asyncio.Lock()


class ClientPool:
    """LRU pool of AsyncSession keyed by auth_token.

    Sessions are reused across requests to skip cold TLS handshake. When the
    pool exceeds `CLIENT_POOL_MAX`, the least-recently-used entry is evicted
    and its session closed.
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

    async def acquire(self, auth_token: str) -> tuple[AsyncSession, asyncio.Lock]:
        """Get or create a pooled session.

        Returns:
            (session, per_token_lock) — caller must hold the lock for the
            duration of the request to avoid concurrent use of one session.
        """
        async with self._lock:
            now = time.time()
            # Expire stale entries first
            stale = [k for k, e in self._cache.items() if (now - e.last_used) > CLIENT_POOL_TTL]
            for k in stale:
                old = self._cache.pop(k)
                try:
                    await old.session.close()
                except Exception:  # noqa: BLE001
                    pass

            entry = self._cache.get(auth_token)
            if entry:
                self._cache.move_to_end(auth_token)
                entry.last_used = now
                return entry.session, entry.lock

            # Build new session with random UA + proxy
            headers = {**DEFAULT_HEADERS, "user-agent": random_user_agent()}
            proxy = random_proxy()
            kwargs: dict[str, Any] = dict(
                cookies={"auth_token": auth_token, "ct0": gen_ct0()},
                headers=headers,
                timeout=20.0,
                impersonate="chrome124",
                allow_redirects=True,
            )
            if proxy:
                kwargs["proxies"] = {"http": proxy, "https": proxy}
            session = AsyncSession(**kwargs)
            entry = _Entry(session)
            self._cache[auth_token] = entry

            # Evict LRU if over capacity
            while len(self._cache) > CLIENT_POOL_MAX:
                lru_key, lru_entry = self._cache.popitem(last=False)
                try:
                    await lru_entry.session.close()
                except Exception:  # noqa: BLE001
                    pass

            return session, entry.lock

    async def invalidate(self, auth_token: str) -> None:
        """Drop session (e.g., on 401/403) so next request gets fresh TLS."""
        async with self._lock:
            entry = self._cache.pop(auth_token, None)
        if entry:
            try:
                await entry.session.close()
            except Exception:  # noqa: BLE001
                pass

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
    """
    pool = ClientPool.get()
    session, lock = await pool.acquire(auth_token)
    async with lock:
        yield session

