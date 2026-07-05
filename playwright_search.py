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
import json
import logging
import os
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

# Cap concurrent Playwright operations (browser pages aktif). Default 4 pages —
# tweak via env. Headless Chrome ~80-150MB per page, jadi 4 = ~600MB RAM peak.
PLAYWRIGHT_MAX_CONCURRENT = int(os.environ.get("PLAYWRIGHT_MAX_CONCURRENT", "4"))


# ──────────────────────────── In-flight coalescer ────────────────────────────


class _InFlightCoalescer:
    """Deduplicate identical concurrent Playwright calls.

    Two callers asking for the same (op, key, vars) at the same time share
    one page — the second caller waits for the first's result instead of
    spawning its own Chromium page (saving ~80-150MB + 3-6s).
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Event] = {}
        self._results: dict[str, dict[str, Any]] = {}
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
            existing = self._pending.get(key)
            if existing is not None:
                pass  # Another caller is running — wait below
            else:
                self._pending[key] = asyncio.Event()

        if existing is not None:
            # Waiter path: block until executor stores result, then take it
            await existing.wait()
            stored = self._results.pop(key, None)
            if stored is None:
                raise RuntimeError(f"coalesced call for {key} failed upstream")
            if isinstance(stored, Exception):
                raise stored
            return stored

        # Executor path: run fn(), store result (or exception), wake waiters
        exc: BaseException | None = None
        result: dict[str, Any] | None = None
        try:
            result = await fn()
            return result
        except BaseException as e:
            exc = e
            raise
        finally:
            # Always store something before setting event, so waiters never
            # hang. Store exception object on failure so waiters see it.
            async with self._lock:
                if exc is not None:
                    self._results[key] = exc  # waiter will re-raise
                elif result is not None:
                    self._results[key] = result
                self._pending.pop(key, None).set()


_coalescer = _InFlightCoalescer()


def _search_key(auth_token: str, q: str, search_type: SearchType) -> str:
    import hashlib
    from app.config import token_key
    return f"search:{token_key(auth_token)}:{q}:{search_type}"


def _fetch_key(auth_token: str, navigate_url: str, match_path: str | list[str], click_selector: str | None = None) -> str:
    import hashlib
    from app.config import token_key
    cs = click_selector or ""
    mp = match_path if isinstance(match_path, str) else "|".join(sorted(match_path))
    return f"fetch:{token_key(auth_token)}:{navigate_url}:{mp}:{cs}"


def _click_key(auth_token: str, navigate_url: str, click_selector: str, match_response_substr: str | list[str] | None = None) -> str:
    import hashlib
    from app.config import token_key
    mr = ""
    if match_response_substr:
        mr = match_response_substr if isinstance(match_response_substr, str) else "|".join(sorted(match_response_substr))
    return f"click:{token_key(auth_token)}:{navigate_url}:{click_selector}:{mr}"


class PlaywrightPool:
    """Singleton browser instance — launch sekali, share antar request.

    Tambah semaphore untuk cap concurrent page operations.
    """

    _instance: Optional["PlaywrightPool"] = None

    def __init__(self) -> None:
        self._pw = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(PLAYWRIGHT_MAX_CONCURRENT)

    @classmethod
    def get(cls) -> "PlaywrightPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._sem

    async def ensure(self) -> Browser:
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                )
            return self._browser

    async def warmup(self) -> None:
        """Pre-launch browser di startup supaya request pertama tidak nunggu Chromium init."""
        try:
            await self.ensure()
        except Exception:  # noqa: BLE001
            pass

    async def close(self) -> None:
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
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )
    # ct0 — X CSRF token, needed by ton.twitter.com alongside auth_token
    _ct0 = secrets.token_hex(16)
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
                "domain": ".twitter.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "None",
            },
        ]
    )
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
        self._lock = asyncio.Lock()

    @classmethod
    def get(cls) -> "ContextPool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def acquire(self, auth_token: str) -> BrowserContext:
        import time as _t
        async with self._lock:
            entry = self._ctxs.get(auth_token)
            if entry:
                ctx, _ = entry
                # health check: closed contexts have empty pages collection raise
                try:
                    _ = ctx.pages
                    self._ctxs[auth_token] = (ctx, _t.time())
                    return ctx
                except Exception:  # noqa: BLE001
                    self._ctxs.pop(auth_token, None)

            browser = await PlaywrightPool.get().ensure()
            ctx = await _new_context(browser, auth_token)

            if len(self._ctxs) >= self.MAX:
                oldest = min(self._ctxs.items(), key=lambda kv: kv[1][1])[0]
                old_ctx, _ = self._ctxs.pop(oldest)
                try:
                    await old_ctx.close()
                except Exception:  # noqa: BLE001
                    pass

            self._ctxs[auth_token] = (ctx, _t.time())
            return ctx

    async def invalidate(self, auth_token: str) -> None:
        async with self._lock:
            entry = self._ctxs.pop(auth_token, None)
            if entry:
                try:
                    await entry[0].close()
                except Exception:  # noqa: BLE001
                    pass

    async def close_all(self) -> None:
        async with self._lock:
            for ctx, _ in list(self._ctxs.values()):
                try:
                    await ctx.close()
                except Exception:  # noqa: BLE001
                    pass
            self._ctxs.clear()

    def stats(self) -> dict[str, int]:
        return {"contexts": len(self._ctxs), "max": self.MAX}


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
    key = _click_key(auth_token, navigate_url, click_selector, match_response_substr)
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


async def _click_action_via_browser_impl(
    auth_token: str,
    navigate_url: str,
    click_selector: str,
    confirm_selector: Optional[str] = None,
    match_response_substr: Optional[str | list[str]] = None,
    timeout: float = 25.0,
) -> dict[str, Any]:
    context = await ContextPool.get().acquire(auth_token)
    page = await context.new_page()

    captured: dict[str, Any] = {}
    matchers: list[str] = []
    if match_response_substr:
        matchers = [match_response_substr] if isinstance(match_response_substr, str) else list(match_response_substr)

    async def _on_response(resp: Response) -> None:
        if "data" in captured or "raw" in captured:
            return
        if matchers and not any(m in resp.url for m in matchers):
            return
        try:
            captured["data"] = await resp.json()
            captured["status"] = resp.status
            captured["url"] = resp.url
        except Exception:  # noqa: BLE001
            try:
                captured["raw"] = (await resp.text())[:1000]
                captured["status"] = resp.status
                captured["url"] = resp.url
            except Exception:  # noqa: BLE001
                pass

    page.on("response", lambda r: asyncio.create_task(_on_response(r)))

    try:
        await page.goto(navigate_url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        await asyncio.sleep(2)

        try:
            await page.click(click_selector, timeout=int(timeout * 1000 / 2))
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "error": f"click failed: {e}", "data": None}

        if confirm_selector:
            await asyncio.sleep(1)
            try:
                await page.click(confirm_selector, timeout=5000)
            except Exception:  # noqa: BLE001
                pass

        deadline = asyncio.get_event_loop().time() + timeout
        while "data" not in captured and "raw" not in captured and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.2)

        if "data" not in captured and "raw" not in captured:
            return {"status": "error", "error": "no response captured", "data": None}

        if captured.get("status", 0) >= 400:
            return {
                "status": "error",
                "http_status": captured.get("status"),
                "error": captured.get("data") or captured.get("raw"),
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": captured.get("status", 200),
            "data": captured.get("data") or {"raw": captured.get("raw")},
        }
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass
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
    page = await context.new_page()

    try:
        # Warm: x.com/home → page jadi punya semua cookie + TID generator loaded
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=int(timeout * 1000))
        # Tunggu sampai bundle ready (TID generator init)
        await asyncio.sleep(3)

        # Build fetch args di-eksekusi di context window (CSRF/TID di-inject otomatis)
        if isinstance(body, dict):
            import json as _json
            body_str = _json.dumps(body)
        else:
            body_str = body or ""

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

        cookies = await context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies}

        status_code = result.get("status", 0)
        payload = result.get("body")

        if status_code >= 400:
            return {
                "status": "error",
                "http_status": status_code,
                "error": payload,
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": status_code,
            "data": payload,
        }
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass
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
    page = await context.new_page()

    captured: dict[str, Any] = {}
    matchers = [match_path] if isinstance(match_path, str) else list(match_path)

    async def _on_response(resp: Response) -> None:
        if "data" in captured:
            return
        if not any(m in resp.url for m in matchers):
            return
        try:
            captured["data"] = await resp.json()
            captured["url"] = resp.url
            captured["status"] = resp.status
        except Exception:  # noqa: BLE001
            try:
                captured["raw"] = (await resp.text())[:2000]
                captured["url"] = resp.url
                captured["status"] = resp.status
            except Exception:  # noqa: BLE001
                pass

    page.on("response", lambda r: asyncio.create_task(_on_response(r)))

    try:
        await page.goto(navigate_url, wait_until="domcontentloaded", timeout=int(timeout * 1000))

        if click_selector:
            try:
                await page.click(click_selector, timeout=int(timeout * 1000))
            except Exception:  # noqa: BLE001
                pass

        deadline = asyncio.get_event_loop().time() + timeout
        while "data" not in captured and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.2)

        if "data" not in captured:
            return {
                "status": "error",
                "error": f"timeout: response {match_path} tidak ter-capture",
                "captured_url": captured.get("url"),
                "http_status": captured.get("status"),
                "raw": captured.get("raw"),
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": captured.get("status", 200),
            "captured_url": captured.get("url"),
            "data": captured["data"],
        }
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass
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
    page = await context.new_page()

    captured: dict[str, Any] = {}

    def _is_search_response(resp: Response) -> bool:
        url = resp.url
        return (
            "/i/api/graphql/" in url and "/SearchTimeline" in url
        ) or "/i/api/2/search/adaptive.json" in url

    async def _on_response(resp: Response) -> None:
        if "data" in captured:
            return
        if not _is_search_response(resp):
            return
        try:
            body = await resp.json()
            captured["data"] = body
            captured["url"] = resp.url
            captured["status"] = resp.status
        except Exception:  # noqa: BLE001
            try:
                captured["raw"] = (await resp.text())[:2000]
                captured["url"] = resp.url
                captured["status"] = resp.status
            except Exception:  # noqa: BLE001
                pass

    page.on("response", lambda r: asyncio.create_task(_on_response(r)))

    try:
        f = URL_FILTER.get(search_type, "live")
        from urllib.parse import quote

        url = f"https://x.com/search?q={quote(q)}&src=typed_query&f={f}"
        await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))

        # Tunggu response ke-capture
        deadline = asyncio.get_event_loop().time() + timeout
        while "data" not in captured and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.2)

        if "data" not in captured:
            return {
                "status": "error",
                "error": "timeout: response SearchTimeline/adaptive.json tidak ter-capture",
                "captured_url": captured.get("url"),
                "http_status": captured.get("status"),
                "raw": captured.get("raw"),
                "data": None,
            }

        return {
            "status": "ok",
            "http_status": captured.get("status", 200),
            "captured_url": captured.get("url"),
            "data": captured["data"],
        }
    finally:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass
        # context tetap di pool — jangan close
