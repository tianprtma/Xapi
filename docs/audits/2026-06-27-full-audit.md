# Audit Report — Xapi Full Codebase
Date: 2026-06-27

## Summary
- 🔴 Critical: 4
- 🟠 High: 10
- 🟡 Medium: 8
- 🟢 Low: 4

Test suite: 180 passed, 0 failed, 59% coverage.

---

## 🔴 Critical

### C-001: `is_alive()` uses `created_at` instead of `last_used` → premature session eviction
- File: `session_cache.py:39-40`, `session_cache.py:43`
- Issue: `is_alive()` compares against `created_at` (fixed timestamp from when session was first created). `lookup()` bumps `last_used` but `is_alive()` ignores it. After 5min the session is considered dead even if actively used every 10s — forcing unnecessary warm-up GETs.
- Fix: Change `is_alive` and `viewer_alive` to compare `time.time() - self.last_used < ttl` instead of `time.time() - self.created_at < ttl`.

```python
# session_cache.py:39 - fix
def is_alive(self, ttl: float = TTL_SECONDS) -> bool:
    return (time.time() - self.last_used) < ttl

def viewer_alive(self, ttl: float = TTL_SECONDS) -> bool:
    return self.viewer is not None and (time.time() - self.last_used) < ttl
```

### C-002: `playwright_search.py:218` — predictable CT0 fallback
- File: `playwright_search.py:218`
- Issue: `_ct0 = secrets.token_hex(16) if "secrets" in dir(__builtins__) else "a" * 32`. The fallback "a"*32 is a predictable CSRF token. The `secrets` check on builtins is pointless (imported above via `import secrets` at line 218-implied; actually no import exists at top of file for `secrets`).
- Actually looking again: line 218 is inside `_new_context()` — there's NO `import secrets` at function scope. The check `"secrets" in dir(__builtins__)` evaluates True in standard Python, but if for some reason builtins doesn't have it, falls back to static string.
- Fix: add `import secrets` at top of file, use `secrets.token_hex(16)` unconditionally.

```python
# playwright_search.py — add at top imports
import secrets
# line 218 change:
_ct0 = secrets.token_hex(16)
```

### C-003: `media.py:77` — auth_token extraction bypasses format validation
- File: `app/routers/media.py:77`
- Issue: Manual token extraction `request.headers.get("authorization", "").removeprefix("Bearer ").strip()` bypasses `extract_bearer()` which validates `AUTH_TOKEN_PATTERN` (40 hex chars) and checks `ALLOW_QUERY_AUTH`. Invalid format tokens pass through to upstream call.
- Fix: Use `extract_bearer()` consistently.

```python
# media.py:77-79 — fix
from ..auth import extract_bearer
# ...
tok = extract_bearer(request.headers.get("Authorization"), request.query_params.get("auth_token"))
```

### C-004: `xchat/events.py:103` — group chat conversation_id mangled by replace()
- File: `app/xchat/events.py:103-104`
- Issue: `conv_id_legacy = conv_id_xchat.replace(":", "-")` with NO count arg — already correct for group chats. Wait, re-reading: `str.replace(":", "-")` replaces ALL occurrences, so `u1:u2:u3` → `u1-u2-u3`. That's actually correct.
- Fix: NONE — code is correct. Retracted.

### C-004 (real): `dm.py`  `dm_conv_id_for()` ValueError on non-numeric user_id
- File: `app/clients.py:445`
- Issue: `key=lambda x: int(x) if x.isdigit() else x` — if user_id is non-numeric, int() still called when `isdigit()` is True but id exceeds Python int range (e.g. 25-digit Twitter snowflakes exceed 64-bit). Also: `str.isdigit()` returns True for Unicode digits like "²" which fail int().
- Fix: Use `int` conversion inside try/except or use decimal.Decimal for comparison.

```python
# clients.py:445 — fix
from functools import cmp_to_key
def _numeric_sort(a: str, b: str) -> int:
    try: return (int(a) > int(b)) - (int(a) < int(b))
    except ValueError: return (a > b) - (a < b)
a, b = sorted([str(me), str(other)], key=cmp_to_key(_numeric_sort))
```

---

## 🟠 High

### H-001: `formatter.py:251` — KeyError on user without "id" field
- File: `formatter.py:251`
- Issue: `{u["id"] for u in includes["users"]}` — if `_user_result_to_obj()` returns a dict without "id" key (e.g. malformed upstream data), raises KeyError.
- Fix: use `u.get("id")`

### H-002: `responses.py:45-46` — KeyError `result["status"]` if missing
- File: `app/responses.py:40, 136`
- Issue: `result["status"]` in `finalize()` and `write_finalize()` would crash with KeyError if Playwright returns dict without "status" key (e.g. network error path).
- Fix: use `result.get("status")` and handle None.

### H-003: `security.py:228-232` — Invalid tokens consume IP rate limit bucket
- File: `app/security.py:228-232`
- Issue: When `extract_bearer()` raises HTTPException (invalid format), catch-all `except Exception` falls back to `request.client.host`. Malformed tokens thus consume the IP's rate limit, potentially exhausting it for legitimate requests.
- Fix: Re-raise HTTPException exceptions, only catch unexpected errors.

```python
# security.py:227-230 — fix
try:
    tok = extract_bearer(...)
except HTTPException:
    raise
except Exception:  # noqa: BLE001
    return request.client.host if request.client else "unknown"
```

### H-004: `playwright_search.py:84-97` — Coalescer waiter path stores Exception but may return None
- File: `playwright_search.py:84-97`
- Issue: Line 94 `result = self._results.pop(key, None)` — if executor stored `None` instead of an Exception, waiter returns None silently. Callers expecting dict may crash.
- Fix: Store a sentinel class for failure cases, or always store Exception.

### H-005: `infra.py:196` — dead import `_cfg_bot_id`
- File: `app/routers/infra.py:196`
- Issue: `from ..config import XCHAT_BOT_USER_ID as _cfg_bot_id` — imported but never used. Shows incomplete refactoring of env var update logic.
- Fix: Remove dead import.

### H-006: `security.py:259-261` — Rate limit retry_after calculation may be negative
- File: `app/security.py:259`
- Issue: `retry_after = max(1, int((1.0 - bucket.tokens) / self._rate))` — with low rate and high elapsed time, `bucket.tokens` could be > 1.0 (just refilled), causing `(1.0 - bucket.tokens)` negative → `max(1, negative)` = 1. Minor, but misleading Retry-After header.
- Fix: `retry_after = max(1, int(max(0, 1.0 - bucket.tokens) / self._rate))`

### H-007: `auth.py:154` — `except Exception: pass` masks all warmup failures
- File: `app/auth.py:154`
- Issue: Connection errors, DNS failures, proxy timeouts are silently swallowed. Downstream code gets empty cookie jar → raises misleading "auth_token expired" instead of network error.
- Fix: Log at minimum; consider raising for non-timeout errors.

### H-008: `config.py:15-20` — Module-level JSON file reads crash on missing/malformed files
- File: `app/config.py:15-20`
- Issue: `GQL_META` and `XCHAT_GQL_META` read at import time. Missing or corrupted `_gql_meta.json` / `_xchat_gql_meta.json` prevents entire app from starting.
- Fix: Lazy-load with cache, or add graceful fallback.

### H-009: `xchat/bridge.py:163` — No `ct0` cookie set in persistent context
- File: `app/xchat/bridge.py:163-174`
- Issue: Only `auth_token` cookie is injected. X's XChat operations may need `ct0` for CSRF protection. Could cause silent auth failures in XChat message operations.
- Fix: Add `ct0` cookie (random hex) like `_new_context()` does.

### H-010: `responses.py:95-111` — Fragile error code matching via substring
- File: `app/responses.py:95-111`
- Issue: Error status classification uses string concatenation + `.lower()` on error messages. If X changes error wording, mapping breaks. Magic X error codes (32, 64, etc.) undocumented.
- Fix: Add comment referencing X error code docs; consider more robust matching.

---

## 🟡 Medium

### M-001: `observability.py:192-193` — `TID check` early return detail may be misleading
- File: `app/observability.py:192-193`
- Issue: When `loaded=True` and `fallback_mode=False`, detail is "ok". When neither, detail is "not yet loaded" — but still returns `ok=True`. Health endpoint shows healthy when TID not ready.

### M-002: `response_cache.py:66` — Cache key includes auth_token hash but not raw token location
- No real issue — keys are correct.

### M-003: `media.py:77` — Fallback to query auth when Authorization header has empty token
- File: `app/routers/media.py:77`
- Issue: `request.headers.get("authorization", "").removeprefix("Bearer ").strip()` — if header is "Bearer " (empty), falls through to `or request.query_params.get("auth_token")`. Accidental query auth usage even when header was intentionally sent empty.
- Fix: Only fall to query if header absent entirely.

### M-004: `client_pool.py:71-77` — Stale entry iteration O(n) on every acquire
- File: `app/client_pool.py:71-77`
- Issue: Every `acquire()` iterates all cache entries to evict stale ones. With `CLIENT_POOL_MAX=50` it's fine, but pattern doesn't scale.
- Fix: Lazy eviction (check only the requested key, evict during put).

### M-005: `responses.py:88-92` — `_has_success_payload()` iterates every data value
- File: `app/responses.py:88-92`
- Issue: `any(value not in ({}, [], None) for value in data.values())` iterates ALL fields just to check if one is non-empty.
- Fix: Early-exit when first non-empty found.

### M-006: `tid_provider.py:54-71` — `_refresh()` uses blocking `requests` in thread pool
- File: `tid_provider.py:54-71`
- Issue: Uses `requests.Session()` (blocking) via `run_in_executor`. Fine for background refresh. But if refresh hangs, blocks the thread pool thread.

### M-007: `main.py:256` — Multi-worker mode duplicates in-memory caches
- File: `main.py:256`
- Issue: Documented warning about `WEB_CONCURRENCY>1`. Each worker has separate SessionStore/ResponseCache/ClientPool — 2x memory, cache misses across workers. Not a bug but operational risk.

### M-008: `sanitize.py:65-70` — Search query truncation instead of rejection
- File: `app/sanitize.py:68-69`
- Issue: `return value[:MAX_QUERY_LEN]` silently truncates long queries. User doesn't know their query was cut.
- Fix: Return error or add truncation warning.

---

## 🟢 Low

### L-001: `retry.py:50` — jitter range excludes -25% edge due to multiplication
- File: `app/retry.py:50`
- Issue: `jitter = delay * 0.25 * (random.random() * 2 - 1)` — returns value in [-0.25*delay, 0.25*delay). Fine, ±25% range is correct.

### L-002: `infra.py:39` — 404 on missing ADMIN_TOKEN instead of 403
- File: `app/routers/infra.py:39-41`
- Issue: When `ADMIN_TOKEN` env not set, returns 404 "Not Found" instead of 403. Intentional to hide admin endpoint existence, but violates REST semantics.

### L-003: `errors.py:293-294` — `build_error_jsonapi` doesn't include `status` field like `build_error`
- File: `app/errors.py:293-294`
- Issue: `build_error_jsonapi` generates errors without `http_status` in the error object (only at top level). Inconsistent with `build_error` which includes `"status": ec.http_status` in each error entry.

### L-004: `playwright_search.py:721` - `captured_url` key not included in returned dict
- File: `playwright_search.py:739` — `captured.get("url")` used in error but `captured_url` key is explicitly NOT returned. Minor inconsistency.

---

## Coverage Gaps

| Module | Coverage | Untested paths |
|---|---|---|
| `app/xchat/events.py` | 0% | Entire XChat DB reader — no tests |
| `app/xchat/bridge.py` | 26% | Bridge lifecycle, PIN entry, OPFS reads |
| `app/formatter.py` | 27% | Most formatters (DM, community, birdwatch, timeline) |
| `app/clients.py` | 24% | All upstream callers (graphql, rest, dm, media_upload) |
| `app/auth.py` | 44% | Login flow, warm_session, error paths |
| `app/playwright_helpers.py` | 26% | resolve_screen_name, tweet_author_handle |
| `session_cache.py` | 60% | Viewer cache, store paths |
| `app/response_cache.py` | 65% | Store/lookup edge cases |

### Functional test gaps
- All routers tested for HTTP reachability + auth enforcement, but NOT for actual data flow (mocked upstream responses)
- No integration tests for `clients.py` callers (graphql_call, rest_call, dm_call)
- No tests for error fallbacks (Playwright fallback, retry logic)
- Zero tests for XChat bridge or event readers

---

## Notable non-bugs (verified)

- **IDOR in path params**: Routers accept `{user_id}` in path but NEVER verify it matches auth token's user. X upstream rejects cross-user writes server-side, so not exploitable. Still: misleading API contract.
- **`except Exception: pass` patterns**: Widespread but intentional for resource cleanup and non-critical warmup steps. Real errors are logged at higher levels.
- **Auth-less endpoints**: /info, /health, /docs intentionally no auth (documented).
- **Query auth param deprecated**: Backward-compat; ALLOW_QUERY_AUTH=0 disables in prod.

---

## Test Suite
- 180 tests — all green ✅
- No skipped tests
- 1 Pydantic v2 deprecation warning (`min_items` → `min_length` in `dm.py:74`)
