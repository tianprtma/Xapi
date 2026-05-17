"""Retry decorator/helper for upstream X calls.

Retry on transient errors (429, 502, 503, 504) with exponential backoff + jitter.
Don't retry: 4xx (except 429), 401/403 (auth dead — invalidate session instead).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable

from .config import RETRY_BASE_DELAY, RETRY_MAX_ATTEMPTS, RETRY_MAX_DELAY


# Status codes yang worth retry (transient upstream issues)
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


async def with_retry(
    fn: Callable[..., Awaitable[dict[str, Any]]],
    *args: Any,
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    **kwargs: Any,
) -> dict[str, Any]:
    """Call `fn(*args, **kwargs)` with retry on transient failures.

    `fn` must return a result dict with `status` + `http_status`. Retries on
    `status == "error"` and `http_status in RETRYABLE_STATUS`.

    Backoff: `base * 2^(attempt-1)` ± 25% jitter, capped at `RETRY_MAX_DELAY`.
    """
    attempt = 0
    last_result: dict[str, Any] = {}
    while attempt < max_attempts:
        attempt += 1
        last_result = await fn(*args, **kwargs)

        if last_result.get("status") != "error":
            return last_result
        http_status = last_result.get("http_status")
        if http_status not in RETRYABLE_STATUS:
            return last_result

        if attempt >= max_attempts:
            break

        # Exponential backoff with jitter
        delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
        jitter = delay * 0.25 * (random.random() * 2 - 1)  # ±25%
        await asyncio.sleep(max(0.1, delay + jitter))

    return last_result
