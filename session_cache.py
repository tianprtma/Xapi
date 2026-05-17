"""
In-memory cache untuk session X (cookies + ct0 + viewer profile) per auth_token.

Tujuan: skip GET /home warm-up untuk request berikutnya selama session masih
hidup. ct0 X tahan ~24 jam, tapi kita pakai TTL 5 menit biar konservatif
(cookie __cf_bm refresh ~30 menit, kalau di-reuse terlalu lama bisa kena CF).

Viewer profile (untuk /2/users/me) juga di-cache 5 menit di slot terpisah.

Bounded LRU 5000 entries — pas untuk multi-tenant proxy dengan ratusan-ribuan
sessions; lebih dari itu, oldest entries di-evict.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional


TTL_SECONDS = 300  # 5 menit
MAX_SESSIONS = 5000


@dataclass
class Session:
    auth_token: str
    ct0: str
    cookies: dict[str, str]  # full cookie jar (auth_token, ct0, twid, guest_id, dll)
    user_id: Optional[str] = None
    viewer: Optional[dict[str, Any]] = None  # cached viewer profile (login result)
    viewer_at: float = 0.0  # timestamp when viewer was cached
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    def is_alive(self, ttl: float = TTL_SECONDS) -> bool:
        return (time.time() - self.created_at) < ttl

    def viewer_alive(self, ttl: float = TTL_SECONDS) -> bool:
        return self.viewer is not None and (time.time() - self.viewer_at) < ttl


class SessionStore:
    """Singleton bounded LRU cache. Key = auth_token, value = Session."""

    _instance: Optional["SessionStore"] = None

    def __init__(self) -> None:
        self._cache: OrderedDict[str, Session] = OrderedDict()
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> "SessionStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def lookup(self, auth_token: str, ttl: float = TTL_SECONDS) -> Optional[Session]:
        async with self._lock:
            sess = self._cache.get(auth_token)
            if sess and sess.is_alive(ttl):
                sess.last_used = time.time()
                self._cache.move_to_end(auth_token)
                return sess
            if sess:
                self._cache.pop(auth_token, None)
            return None

    async def store(
        self,
        auth_token: str,
        ct0: str,
        cookies: dict[str, str],
        user_id: Optional[str] = None,
    ) -> Session:
        async with self._lock:
            sess = Session(
                auth_token=auth_token,
                ct0=ct0,
                cookies=cookies,
                user_id=user_id,
            )
            self._cache[auth_token] = sess
            self._cache.move_to_end(auth_token)
            while len(self._cache) > MAX_SESSIONS:
                self._cache.popitem(last=False)
            return sess

    async def store_viewer(self, auth_token: str, viewer_payload: dict[str, Any]) -> None:
        """Cache viewer/login result untuk /2/users/me fast path."""
        async with self._lock:
            sess = self._cache.get(auth_token)
            if sess:
                sess.viewer = viewer_payload
                sess.viewer_at = time.time()
                self._cache.move_to_end(auth_token)

    async def lookup_viewer(self, auth_token: str, ttl: float = TTL_SECONDS) -> Optional[dict[str, Any]]:
        async with self._lock:
            sess = self._cache.get(auth_token)
            if sess and sess.viewer_alive(ttl):
                sess.last_used = time.time()
                self._cache.move_to_end(auth_token)
                return sess.viewer
            return None

    async def invalidate(self, auth_token: str) -> None:
        async with self._lock:
            self._cache.pop(auth_token, None)

    async def stats(self) -> dict[str, int]:
        async with self._lock:
            now = time.time()
            alive = sum(1 for s in self._cache.values() if s.is_alive())
            viewers = sum(1 for s in self._cache.values() if s.viewer_alive())
            return {
                "total": len(self._cache),
                "alive": alive,
                "expired": len(self._cache) - alive,
                "viewer_cached": viewers,
                "max_sessions": MAX_SESSIONS,
            }
