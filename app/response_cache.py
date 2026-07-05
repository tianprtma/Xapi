"""In-memory response cache for read-only GraphQL ops.

Pakai tuple key (operation, vars_json, auth_token) untuk hot path lookup —
skip SHA-256 yang dulu ~1µs/lookup. Tetap aman karena dict di-akses internal,
token tidak ke-leak ke log/disk.

Bounded LRU (default 2000 entries) untuk avoid unbounded growth.

NOTE: WORKER=1 — cache per-worker. Multi-worker = duplicate cache.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from typing import Any, Optional

from .config import RESPONSE_CACHE_TTL, token_key


# Operations yang aman di-cache (read-only, deterministic given vars + token).
CACHEABLE_OPS = frozenset({
    "UserByScreenName",
    "UserByRestId",
    "TweetResultByRestId",
    "TweetDetail",
    "ListMembers",
    "ListLatestTweetsTimeline",
    "ListsManagementPageTimeline",
    "BookmarkFoldersSlice",
    "CommunityByRestId",
})

# Playwright endpoints — di-cache via op name "_pw_<endpoint>" supaya
# bottleneck headless Chrome (3-6s/call) tidak hit upstream berulang.
PLAYWRIGHT_CACHEABLE_OPS = frozenset({
    "_pw_search",
    "_pw_user_by_id",
    "_pw_mentions",
    "_pw_user_followers",
    "_pw_user_tweets_replies",
})

ALL_CACHEABLE_OPS = CACHEABLE_OPS | PLAYWRIGHT_CACHEABLE_OPS

# Bound size: 2000 entries default (~2-4MB at 1-2KB payload avg).
MAX_CACHE_ENTRIES = 2000


def _key(operation: str, variables: dict[str, Any], auth_token: str) -> tuple:
    """Stable tuple key. Hashes auth_token so plaintext doesn't sit in memory."""
    return (operation, json.dumps(variables, sort_keys=True, default=str), token_key(auth_token))


class ResponseCache:
    """Singleton in-memory TTL+LRU cache for GraphQL response dicts.

    OrderedDict + move_to_end = LRU; bounded to MAX_CACHE_ENTRIES.
    """

    _instance: "ResponseCache | None" = None

    def __init__(self) -> None:
        self._cache: OrderedDict[tuple, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    @classmethod
    def get(cls) -> "ResponseCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def is_cacheable(operation: str) -> bool:
        return RESPONSE_CACHE_TTL > 0 and operation in ALL_CACHEABLE_OPS

    async def lookup(
        self,
        operation: str,
        variables: dict[str, Any],
        auth_token: str,
    ) -> Optional[dict[str, Any]]:
        if not self.is_cacheable(operation):
            return None
        key = _key(operation, variables, auth_token)
        async with self._lock:
            entry = self._cache.get(key)
            if not entry:
                self._misses += 1
                return None
            stored_at, payload = entry
            if (time.time() - stored_at) > RESPONSE_CACHE_TTL:
                self._cache.pop(key, None)
                self._misses += 1
                return None
            # LRU touch
            self._cache.move_to_end(key)
            self._hits += 1
            return payload

    async def store(
        self,
        operation: str,
        variables: dict[str, Any],
        auth_token: str,
        payload: dict[str, Any],
    ) -> None:
        if not self.is_cacheable(operation):
            return
        if payload.get("status") not in ("ok", "valid"):
            return
        key = _key(operation, variables, auth_token)
        async with self._lock:
            self._cache[key] = (time.time(), payload)
            self._cache.move_to_end(key)
            # Bounded LRU: drop oldest sampai size <= MAX.
            while len(self._cache) > MAX_CACHE_ENTRIES:
                self._cache.popitem(last=False)

    async def stats(self) -> dict[str, Any]:
        async with self._lock:
            now = time.time()
            alive = sum(
                1 for stored_at, _ in self._cache.values()
                if (now - stored_at) <= RESPONSE_CACHE_TTL
            )
            total_lookups = self._hits + self._misses
            hit_rate = (self._hits / total_lookups) if total_lookups else 0.0
            return {
                "size": len(self._cache),
                "alive": alive,
                "max_entries": MAX_CACHE_ENTRIES,
                "ttl_seconds": RESPONSE_CACHE_TTL,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
                "cacheable_ops": sorted(CACHEABLE_OPS),
                "playwright_ops": sorted(PLAYWRIGHT_CACHEABLE_OPS),
            }
