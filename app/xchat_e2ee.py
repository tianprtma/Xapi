"""
XChat E2EE Resolver & PIN Unlocker for Xapi.

Handles:
1. Unlocking XChat E2EE `/i/chat` session using 4-8 digit `dm_pin` inside `ContextPool`.
2. Decrypting `_xchat_encrypted: True` messages and inbox conversation previews via Shadow DOM.
3. Extracting E2EE `blob:` images from the browser context into an in-memory cache
   so `/2/dm_conversations/media/xchat/{media_id}/{resource_id}` serves raw bytes over HTTP.
4. Sending DMs and approving message requests on E2EE conversations when needed.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import secrets
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

import playwright_search
from playwright_search import XChatContextPool, PlaywrightPool

log = logging.getLogger(__name__)

# Cache decrypted E2EE blob images: media_id -> (bytes, content_type, timestamp)
_E2EE_MEDIA_CACHE: dict[str, tuple[bytes, str, float]] = {}
_E2EE_MEDIA_TTL = 900.0  # 15 minutes
_E2EE_MEDIA_MAX = 200

# Selectors inside x.com/i/chat (and [data-testid="xchatEmbedRoute"] shadowRoot)
PIN_INPUT_SELECTOR = (
    'input[data-testid^="pin-input-"], '
    'input[type="password"][maxlength="1"], '
    'input[inputmode="numeric"][maxlength="1"], '
    'input[autocomplete="one-time-code"]'
)
DM_CONTAINER_SELECTOR = (
    '[data-testid="dm-container"], '
    '[data-testid="dm-conversation-scroller"], '
    '[data-testid="dm-message-list"], '
    '[data-testid="DMDrawer"], '
    'a[href*="/i/chat/"]'
)
DM_COMPOSER_SELECTOR = (
    '[data-testid="dm-composer-textarea"], '
    '[data-testid="dmComposerTextInput"], '
    'textarea[placeholder], '
    '[contenteditable="true"][role="textbox"]'
)


def resolve_dm_pin(query_pin: Optional[str] = None, header_pin: Optional[str] = None) -> Optional[str]:
    """Resolve DM PIN from query param, X-DM-Pin header, or DM_PIN environment variable."""
    pin = (query_pin or header_pin or os.environ.get("DM_PIN") or "").strip()
    if pin and pin.isdigit() and 4 <= len(pin) <= 8:
        return pin
    return None


def cache_e2ee_media(
    data_url: str,
    key_hint: str = "",
    *,
    kind: str = "photo",
    duration_ms: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    thumbnail_data_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Store browser-extracted E2EE media and return a safe proxy descriptor."""
    if not data_url or not data_url.startswith("data:"):
        return None
    try:
        header, b64_data = data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "").strip() or "image/png"
        raw_bytes = base64.b64decode(b64_data)
    except Exception:
        return None
    if not raw_bytes:
        return None

    kind = "video" if kind in ("video", "animated_gif") else "photo"
    now = time.time()
    expired = [k for k, (_, _, ts) in _E2EE_MEDIA_CACHE.items() if now - ts > _E2EE_MEDIA_TTL]
    for k in expired:
        _E2EE_MEDIA_CACHE.pop(k, None)
    while len(_E2EE_MEDIA_CACHE) >= _E2EE_MEDIA_MAX:
        oldest_key = min(_E2EE_MEDIA_CACHE.items(), key=lambda kv: kv[1][2])[0]
        _E2EE_MEDIA_CACHE.pop(oldest_key, None)

    media_id = hashlib.sha256(
        (key_hint or secrets.token_hex(8)).encode("utf-8") + raw_bytes[:256]
    ).hexdigest()[:20]
    if kind == "video":
        if mime not in ("video/mp4", "video/quicktime"):
            return None
        ext = "mp4" if mime == "video/mp4" else "mov"
        resource_prefix = "vid"
    else:
        ext = (
            "jpg" if ("jpeg" in mime or "jpg" in mime)
            else ("webp" if "webp" in mime else ("gif" if "gif" in mime else "png"))
        )
        resource_prefix = "img"
    resource_id = f"{resource_prefix}_{media_id}.{ext}"
    _E2EE_MEDIA_CACHE[media_id] = (raw_bytes, mime, now)
    result: dict[str, Any] = {
        "media_id": media_id,
        "kind": kind,
        "mime": mime,
        "url": f"https://ton.x.com/1.1/ton/data/dm/xchat/{media_id}/{resource_id}",
        "proxy_path": f"/2/dm_conversations/media/xchat/{media_id}/{resource_id}",
        "duration_ms": duration_ms,
        "width": width,
        "height": height,
        "byte_size": len(raw_bytes),
    }
    if thumbnail_data_url and kind == "video":
        thumb = cache_e2ee_media(
            thumbnail_data_url,
            key_hint=f"{key_hint}:thumbnail",
            kind="photo",
        )
        if thumb:
            result["thumbnail_proxy_path"] = thumb["proxy_path"]
    return {k: v for k, v in result.items() if v is not None}


def get_cached_e2ee_media(media_id: str) -> Optional[tuple[bytes, str]]:
    """Retrieve cached E2EE media bytes & content_type by media_id."""
    entry = _E2EE_MEDIA_CACHE.get(media_id)
    if not entry:
        return None
    raw_bytes, mime, ts = entry
    if time.time() - ts > _E2EE_MEDIA_TTL:
        _E2EE_MEDIA_CACHE.pop(media_id, None)
        return None
    return raw_bytes, mime


async def _ensure_pin_unlocked(page: Any, dm_pin: Optional[str]) -> bool:
    """
    Wait for either XChat container or PIN prompt on the current page.
    If PIN prompt is detected and `dm_pin` is provided, enter the PIN and wait for redirect.
    """
    # Wait up to 12s for either PIN page/inputs or DM container to appear
    try:
        state = await page.wait_for_function(
            """({pinSel, dmSel}) => {
                const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                const root = host?.shadowRoot || document;
                if (window.location.href.includes('/pin/') || root.querySelectorAll(pinSel).length >= 4) {
                    return 'pin';
                }
                if (root.querySelector(dmSel) || document.querySelector(dmSel)) {
                    return 'ready';
                }
                return false;
            }""",
            arg={"pinSel": PIN_INPUT_SELECTOR, "dmSel": DM_CONTAINER_SELECTOR},
            timeout=12000,
        )
        state_val = await state.json_value()
    except Exception:
        state_val = "unknown"

    if state_val == "ready" and "/pin/" not in page.url:
        # XChat merender shell dm-container sementara sebelum redirect ke
        # gate PIN — 'ready' prematur membuat pin tidak pernah diketik dan
        # inbox kosong. R84: konfirmasi stabil via POLL CEPAT (bukan sleep
        # mati 2.5s yang dibayar setiap fetch): tunggu kondisi tetap 'ready'
        # DAN link percakapan muncul selama 1.2s. Gate PIN transient yang
        # muncul akan menggagalkan poll → lanjut jalur unlock. Shell kosong
        # (tanpa link) tetap memakai jalur hati-hati lama.
        try:
            pin_check = await page.evaluate(
                """(pinSel) => {
                    const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                    const root = host?.shadowRoot || document;
                    return {
                        gate: window.location.href.includes('/pin/')
                              || root.querySelectorAll(pinSel).length >= 4,
                        links: root.querySelectorAll('a[href*="/i/chat/"]').length,
                    };
                }""",
                PIN_INPUT_SELECTOR,
            )
            if pin_check.get("gate"):
                log.info("XChat shell transient terdeteksi — lanjut unlock PIN")
                state_val = "pin"
            elif pin_check.get("links"):
                # R84: stabil-cepat — poll hingga 1.2s; gate transient yang
                # menyusul muncul sebagai 'pin'.
                try:
                    stable = await page.wait_for_function(
                        """(pinSel) => {
                            const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                            const root = host?.shadowRoot || document;
                            if (window.location.href.includes('/pin/')
                                || root.querySelectorAll(pinSel).length >= 4) {
                                return 'pin';
                            }
                            return root.querySelectorAll('a[href*="/i/chat/"]').length > 0;
                        }""",
                        arg=PIN_INPUT_SELECTOR,
                        timeout=1200,
                    )
                    stable_val = await stable.json_value()
                    if stable_val == "pin":
                        log.info("Gate PIN muncul saat konfirmasi cepat — lanjut unlock")
                        state_val = "pin"
                except Exception:
                    # Poll timeout tanpa gate = tetap ready (link sudah ada).
                    pass
            else:
                state_val = "pin"  # tidak ada isi → kemungkinan besar gate menyusul
        except Exception:  # noqa: BLE001
            pass
        if state_val == "ready" and "/pin/" not in page.url:
            return True

    # Check if PIN entry is needed
    needs_pin = "/pin/" in page.url or state_val == "pin"
    if not needs_pin:
        has_pin_inputs = await page.evaluate(
            """(pinSel) => {
                const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                const root = host?.shadowRoot || document;
                return root.querySelectorAll(pinSel).length >= 4;
            }""",
            PIN_INPUT_SELECTOR,
        )
        needs_pin = bool(has_pin_inputs)

    if not needs_pin:
        return True

    if not dm_pin:
        log.warning("XChat redirected to PIN page (/pin/), but no dm_pin was provided")
        return False

    log.info("Unlocking XChat E2EE PIN (%d digits)...", len(dm_pin))
    # Wait for PIN inputs to render inside shadowRoot or document
    try:
        await page.wait_for_function(
            """(pinSel) => {
                const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                const root = host?.shadowRoot || document;
                return root.querySelectorAll(pinSel).length >= 4;
            }""",
            arg=PIN_INPUT_SELECTOR,
            timeout=10000,
        )
    except Exception:
        await asyncio.sleep(2.0)

    for idx, digit in enumerate(dm_pin):
        focused = await page.evaluate(
            """({pinSel, index}) => {
                const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                const root = host?.shadowRoot || document;
                const inputs = root.querySelectorAll(pinSel);
                const input = inputs[index];
                if (!input) return false;
                input.focus();
                return true;
            }""",
            {"pinSel": PIN_INPUT_SELECTOR, "index": idx},
        )
        if not focused:
            break
        await page.keyboard.type(digit, delay=60)
        await asyncio.sleep(0.15)

    await asyncio.sleep(0.5)
    await page.keyboard.press("Enter")

    # Wait for PIN page to clear and DM container to appear. XChat recovery
    # unlock keeps the URL on /pin/recovery while the inbox renders — judge
    # success by DM-container presence, not by the URL alone.
    try:
        await page.wait_for_function(
            """(dmSel) => {
                const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                const root = host?.shadowRoot || document;
                const dmReady = Boolean(root.querySelector(dmSel) || document.querySelector(dmSel));
                return dmReady;
            }""",
            arg=DM_CONTAINER_SELECTOR,
            timeout=20000,
        )
        await asyncio.sleep(1.5)
        return True
    except Exception as exc:
        log.warning("XChat PIN unlock wait timed out: %s", exc)
        return "/pin/" not in page.url


async def unlock_and_read_xchat_inbox(
    auth_token: str,
    dm_pin: Optional[str],
    my_user_id: Optional[str] = None,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """
    Open https://x.com/i/chat, unlock PIN if needed, and scrape the conversation list
    (including decrypted preview text, unread status, relative ageMs, convHref, profileHref).
    """
    playwright_search.PLAYWRIGHT_ENABLED = True
    async with PlaywrightPool.get().semaphore:
        context = None
        page = None
        try:
            context = await XChatContextPool.get().acquire(auth_token)
            page = await context.new_page()
            await page.goto("https://x.com/i/chat", wait_until="domcontentloaded", timeout=30000)

            # R88: JALUR UTAMA — daftar percakapan dari OPFS sqlite (sama
            # dengan R87). Sinkronisasi websocket sudah berjalan dari /i/chat;
            # tidak perlu menunggu sidebar DOM dirender (tidak pernah muncul
            # di headless XChat baru — wait 10-12s sia-sia per sweep).
            if my_user_id:
                try:
                    db_bytes = await extract_xchat_opfs_db(page, str(my_user_id), context=context)
                    if db_bytes and db_bytes[:15] == b"SQLite format 3":
                        import sqlite3 as _sqlite3
                        import tempfile as _tempfile

                        with _tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
                            tf.write(db_bytes)
                            tmp_path = tf.name
                        try:
                            conn = _sqlite3.connect(tmp_path)
                            rows = query_inbox_rows(
                                conn, str(my_user_id), max_results
                            )
                        finally:
                            conn.close()
                            os.unlink(tmp_path)
                        if rows:
                            log.info(
                                "R88: OPFS sqlite memulihkan %d percakapan inbox",
                                len(rows),
                            )
                            return rows[:max_results]
                        log.debug("R88: OPFS sqlite kosong — lanjut jalur DOM")
                except Exception as opfs_exc:  # noqa: BLE001
                    log.debug("R88: baca OPFS sqlite gagal (%s) — lanjut DOM", opfs_exc)

            unlocked = await _ensure_pin_unlocked(page, dm_pin)
            if not unlocked:
                return []

            # Wait for conversation links to appear
            try:
                await page.wait_for_function(
                    """() => {
                        const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                        const root = host?.shadowRoot || document;
                        return root.querySelectorAll('a[href*="/i/chat/"]').length > 0;
                    }""",
                    timeout=10000,
                )
            except Exception:
                await asyncio.sleep(2.0)

            # Baris inbox ter-render bertahap: nama muncul dulu, teks pesan +
            # aria-description menyusul async. Tanpa tunggu ini, batch scrape
            # mengambil baris yang belum berisi pesan (preview = nama saja).
            try:
                await page.wait_for_function(
                    """() => {
                        const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                        const root = host?.shadowRoot || document;
                        const items = [...root.querySelectorAll('[data-testid^="dm-conversation-item-"]')];
                        if (items.length === 0) return false;
                        return items.every(it => {
                            const aria = it.getAttribute('aria-description')
                                || it.querySelector('[aria-description]')?.getAttribute('aria-description') || '';
                            return aria.length > 0;
                        });
                    }""",
                    timeout=8000,
                )
            except Exception:  # noqa: BLE001
                await asyncio.sleep(2.0)

            collected: dict[str, dict[str, Any]] = {}
            max_scrolls = int(os.environ.get("XCHAT_INBOX_MAX_SCROLLS", "30"))

            for scroll_idx in range(max_scrolls):
                batch = await page.evaluate(
                    """(myId) => {
                        const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                        const root = host?.shadowRoot || document;
                        const parseRelAge = (desc) => {
                            if (!desc || typeof desc !== 'string') return null;
                            const parts = desc.split(',').map(s => s.trim()).filter(Boolean);
                            const STATUS = ['Belum dibaca', 'Unread', 'Dibisukan', 'Muted'];
                            for (let i = parts.length - 1; i >= 0; i--) {
                                const seg = parts[i];
                                if (STATUS.includes(seg)) continue;
                                const rel = seg.match(/^(\\d+)\\s*(detik|menit|jam|hari|minggu|bulan|tahun|second|minute|hour|day|week|month|year|s|m|h|d|w|y)s?$/i);
                                if (rel) {
                                    const n = parseInt(rel[1], 10);
                                    const u = rel[2].toLowerCase();
                                    const unitMs = {
                                        detik: 1000, second: 1000, s: 1000,
                                        menit: 60000, minute: 60000, m: 60000,
                                        jam: 3600000, hour: 3600000, h: 3600000,
                                        hari: 86400000, day: 86400000, d: 86400000,
                                        minggu: 604800000, week: 604800000, w: 604800000,
                                        bulan: 2592000000, month: 2592000000,
                                        tahun: 31536000000, year: 31536000000, y: 31536000000,
                                    }[u];
                                    if (unitMs) return n * unitMs;
                                }
                                const MONTH_RE = /^(\\d{1,2}\\s+\\w{3,}|\\w{3,}\\s+\\d{1,2})(\\s+\\d{4})?$/i;
                                if (MONTH_RE.test(seg)) {
                                    const normSeg = seg.replace(/\\b(jan|feb|mar|apr|mei|jun|jul|agu|ags|sep|sept|okt|nov|des|januari|februari|maret|april|juni|juli|agustus|september|oktober|november|desember)\\b/gi, (m) => ({
                                        jan: 'Jan', januari: 'Jan',
                                        feb: 'Feb', februari: 'Feb',
                                        mar: 'Mar', maret: 'Mar',
                                        apr: 'Apr', april: 'Apr',
                                        mei: 'May',
                                        jun: 'Jun', juni: 'Jun',
                                        jul: 'Jul', juli: 'Jul',
                                        agu: 'Aug', ags: 'Aug', agustus: 'Aug',
                                        sep: 'Sep', sept: 'Sep', september: 'Sep',
                                        okt: 'Oct', oktober: 'Oct',
                                        nov: 'Nov', november: 'Nov',
                                        des: 'Dec', desember: 'Dec',
                                    })[m.toLowerCase()] || m);
                                    const parsed = Date.parse(normSeg + (normSeg.match(/\\d{4}/) ? '' : ' ' + new Date().getFullYear()));
                                    if (!isNaN(parsed)) {
                                        const ageMs = Date.now() - parsed;
                                        if (ageMs < 0) return Date.now() - (parsed - 31536000000);
                                        return ageMs;
                                    }
                                }
                            }
                            return null;
                        };

                        const out = [];
                        const items = root.querySelectorAll('[data-testid^="dm-conversation-item-"]');
                        const nodes = items.length > 0 ? items : root.querySelectorAll('a[href*="/i/chat/"]');
                        for (const node of nodes) {
                            const convLink = node.tagName === 'A' ? node : node.querySelector('a[href*="/i/chat/"]');
                            if (!convLink) continue;
                            const convHref = convLink.getAttribute('href') || '';
                            const m = convHref.match(/\\/i\\/chat\\/(\\d+[:-]\\d+)/);
                            if (!m) continue;
                            const convId = m[1].replace(':', '-');
                            const profileLink = node.querySelector('a[href^="https://x.com/"]');
                            let profileHref = profileLink ? profileLink.getAttribute('href') : null;
                            if (profileHref && profileHref.startsWith('https://x.com/')) {
                                profileHref = '/' + profileHref.replace('https://x.com/', '');
                            }
                            if (!profileHref && myId && convId.includes('-')) {
                                const parts = convId.split('-');
                                const peer = parts[0] === String(myId) ? parts[1] : parts[0];
                                if (peer) profileHref = `/intent/user?user_id=${peer}`;
                            }
                            const textEls = [...node.querySelectorAll('[dir="auto"]')].map(el => (el.textContent || '').trim()).filter(Boolean);
                            const msgCandidates = textEls.filter(t => !t.startsWith('@') && !/^(\\d+\\s*(?:s|m|h|d|w|y|detik|menit|jam|hari)|·)$/i.test(t));
                            const ariaDesc = node.getAttribute('aria-description')
                                || node.querySelector('[aria-description]')?.getAttribute('aria-description')
                                || '';
                            // Preview bersih dari aria_desc: "nama, @handle, <pesan…>, <umur>, <status>".
                            // Ambil slice asli setelah @handle sampai sebelum segmen umur/status
                            // (koma & newline di dalam pesan tetap utuh).
                            const cleanPreview = (aria) => {
                                if (!aria || typeof aria !== 'string') return null;
                                const parts = aria.split(',').map(s => s.trim()).filter(Boolean);
                                if (parts.length < 3 || !parts[1].startsWith('@')) return null;
                                const handleIdx = aria.indexOf(parts[1]);
                                if (handleIdx < 0) return null;
                                let msg = aria.slice(handleIdx + parts[1].length);
                                msg = msg.replace(/^[\\s,]+/, '');
                                const STATUS = '(?:Belum dibaca|Unread|Dibisukan|Muted)';
                                const AGE = '\\\\d+\\\\s*(?:s|m|h|d|w|y|detik|menit|jam|hari|minggu|bulan|tahun|second|minute|hour|day|week|month|year)s?';
                                for (let i = 0; i < 4; i++) {
                                    const stripped = msg.replace(new RegExp('[\\\\s,]*' + STATUS + '[\\\\s,]*$', 'i'), '')
                                                        .replace(new RegExp('[\\\\s,]*' + AGE + '[\\\\s,]*$', 'i'), '');
                                    if (stripped === msg) break;
                                    msg = stripped;
                                }
                                return msg.trim() || null;
                            };
                            const previewText = cleanPreview(ariaDesc)
                                || (msgCandidates.length > 0
                                    ? msgCandidates[msgCandidates.length - 1]
                                    : (node.textContent || '').trim());
                            const ageMs = parseRelAge(ariaDesc);
                            const isUnread = /\\b(Belum dibaca|Unread)\\b/i.test(ariaDesc);
                            out.push({
                                id: convId,
                                conv_href: convHref,
                                profile_href: profileHref,
                                preview_text: previewText,
                                aria_desc: ariaDesc,
                                age_ms: ageMs,
                                is_unread: isUnread,
                            });
                        }
                        return out;
                    }""",
                    my_user_id,
                )
                for item in batch or []:
                    cid = item.get("id")
                    if cid and cid not in collected:
                        collected[cid] = item
                if len(collected) >= max_results:
                    break

                # Scroll down — scroller element bisa berubah antar versi X; pakai
                # pencarian kandidat (bukan satu testid) agar daftar percakapan
                # termaterialisasi penuh (kalau selector meleset, sidebar hanya
                # memberi ~19 baris dan percakapan 'gelap' tak pernah terlihat).
                scrolled = await page.evaluate(
                    """() => {
                        const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                        const root = host?.shadowRoot || document;
                        const candidates = [
                            root.querySelector('[data-testid="dm-conversation-scroller"]'),
                            root.querySelector('[data-testid="DM_ScrollerContainer"]'),
                            ...root.querySelectorAll('[data-testid^="conversation" i]'),
                            ...root.querySelectorAll('*'),
                        ].filter(el => el && el.scrollHeight > el.clientHeight + 300);
                        candidates.sort((a, b) =>
                            (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
                        const scrollerSet = new Set(candidates.slice(0, 6));
                        for (const scroller of candidates.slice(0, 6)) {
                            const prev = scroller.scrollTop;
                            const max = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
                            scroller.scrollTop = Math.min(max, prev + Math.max(400, scroller.clientHeight * 0.8));
                            if (scroller.scrollTop > prev) return true;
                        }
                        return false;
                    }"""
                )
                if not scrolled:
                    break
                await asyncio.sleep(0.8)

            return list(collected.values())[:max_results]
        except Exception as exc:
            log.warning("unlock_and_read_xchat_inbox error: %s", exc)
            return []
        finally:
            if page is not None:
                try:
                    cached_opfs = getattr(context, "_xchat_opfs_page", None) if context else None
                    if page is not cached_opfs:
                        await page.close()
                except Exception:
                    pass
            if context is not None:
                await XChatContextPool.get().release(auth_token, context)


# ── R87: pembacaan XChat via SQLite OPFS ────────────────────────────────────
# XChat generasi baru (Vite + Module Federation) menyimpan pesan di SQLite
# OPFS `backups/chat_<viewer_id>.db` dan menyinkronkannya lewat websocket.
# Tabel dm_entry berisi plain_text SUDAH TERDEKRIPSI + entry_id UUID +
# timestamp epoch-ms + sender_id — mengungguli render DOM yang di headless
# tidak pernah menampilkan baris pesan (hang 60-90s/conv).

_OPFS_DB_JS = """async (fileName) => {
    // R87.1: navigator.storage.getDirectory bisa undefined di page yang baru
    // dibuka dari konteks dingin (API belum ter-expose). Poll hingga siap.
    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
    for (let i = 0; i < 10; i++) {
        if (navigator.storage && navigator.storage.getDirectory) break;
        await sleep(300);
    }
    if (!navigator.storage || !navigator.storage.getDirectory) return null;
    const root = await navigator.storage.getDirectory();
    try {
        const dir = await root.getDirectoryHandle('backups');
        const fh = await dir.getFileHandle(fileName);
        const bytes = new Uint8Array(await (await fh.getFile()).arrayBuffer());
        let bin = '';
        for (let i = 0; i < bytes.length; i += 0x8000) {
            bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        }
        return btoa(bin);
    } catch (e) {
        return null;
    }
}"""


_OPFS_FILE_JS = """async (path) => {
    // R90: baca file OPFS sembarang (mis. media terdekripsi
    // dm-files-<viewer>/decrypted-media-v2/.../<hash>.jpg) sebagai base64.
    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
    for (let i = 0; i < 10; i++) {
        if (navigator.storage && navigator.storage.getDirectory) break;
        await sleep(300);
    }
    if (!navigator.storage || !navigator.storage.getDirectory) return null;
    try {
        const parts = String(path).split('/').filter(Boolean);
        let dir = await navigator.storage.getDirectory();
        for (let i = 0; i < parts.length - 1; i++) {
            dir = await dir.getDirectoryHandle(parts[i]);
        }
        const fh = await dir.getFileHandle(parts[parts.length - 1]);
        const bytes = new Uint8Array(await (await fh.getFile()).arrayBuffer());
        let bin = '';
        for (let i = 0; i < bytes.length; i += 0x8000) {
            bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        }
        return btoa(bin);
    } catch (e) {
        return null;
    }
}"""


async def read_xchat_opfs_file(
    page: Any, path: str, *, context: Any = None
) -> Optional[bytes]:
    """R90: baca bytes file OPFS via path relatif root (reuse page cache R87.2)."""
    target = page
    if context is not None:
        cached = getattr(context, "_xchat_opfs_page", None)
        if cached is not None:
            try:
                _ = cached.url
                target = cached
            except Exception:
                target = page
    b64 = await target.evaluate(_OPFS_FILE_JS, path)
    if not b64 and target is not page:
        b64 = await page.evaluate(_OPFS_FILE_JS, path)
    if not b64:
        return None
    try:
        return base64.b64decode(b64)
    except Exception:
        return None


# R95: cache bytes db OPFS per (context, viewer) dengan TTL pendek. Semua
# percakapan berbagi file db yang sama; membaca ulang 18MB per conv mubazir
# dan membuat fase fetch watch 3-4 menit. TTL pendek menjaga freshness.
_OPFS_DB_CACHE_TTL = float(os.environ.get("XCHAT_OPFS_DB_CACHE_TTL_SEC", "20"))
_OPFS_DB_CACHE: dict[tuple[int, str], tuple[float, bytes]] = {}
# R99: jeda setelah membuka conv agar client sempat mengunduh media ke OPFS.
_MEDIA_TRIGGER_WAIT_SEC = float(os.environ.get("XCHAT_MEDIA_TRIGGER_WAIT_SEC", "8"))


async def extract_xchat_opfs_db(
    page: Any, viewer_id: str, *, context: Any = None, force: bool = False
) -> Optional[bytes]:
    """Baca file SQLite OPFS `backups/chat_<viewer_id>.db` dari halaman X.
    R87.2: navigator.storage.getDirectory hanya ter-expose di PAGE PERTAMA
    yang membuka origin di persistent context — page baru yang dibuka belakangan
    kadang tidak punya API itu (probe 3x: run-1 sukses, run-2/3 undefined).
    Bila berhasil, page disimpan sebagai `_xchat_opfs_page` pada konteks dan
    dipakai ulang untuk pemanggilan berikutnya.
    R95: bytes di-cache per (context, viewer) selama TTL agar fetch watch
    beruntun tidak membaca ulang file 18MB per percakapan.
    R99: force=True melewati cache (baca segar) — dipakai setelah memicu
    unduhan media agar snapshot baru terlihat.
    Kembalikan bytes db, atau None bila file tidak ada."""
    cache_key = (id(context), str(viewer_id)) if context is not None else None
    if not force and cache_key is not None and _OPFS_DB_CACHE_TTL > 0:
        hit = _OPFS_DB_CACHE.get(cache_key)
        if hit is not None and (time.monotonic() - hit[0]) < _OPFS_DB_CACHE_TTL:
            return hit[1]
    target = page
    if context is not None:
        cached = getattr(context, "_xchat_opfs_page", None)
        if cached is not None:
            try:
                _ = cached.url  # page masih hidup?
                target = cached
            except Exception:
                target = page
    b64 = await target.evaluate(_OPFS_DB_JS, f"chat_{viewer_id}.db")
    if not b64 and target is not page:
        # Page cache mungkin basi — coba page baru sekali lagi.
        b64 = await page.evaluate(_OPFS_DB_JS, f"chat_{viewer_id}.db")
        target = page
    if not b64:
        return None
    if context is not None and getattr(context, "_xchat_opfs_page", None) is None:
        try:
            context._xchat_opfs_page = target
        except Exception:
            pass
    try:
        import base64 as _b64
        data = _b64.b64decode(b64)
    except Exception:
        return None
    if cache_key is not None and _OPFS_DB_CACHE_TTL > 0:
        _OPFS_DB_CACHE[cache_key] = (time.monotonic(), data)
    return data


async def debug_clear_and_capture(auth_token: str, dm_pin: Optional[str], conv_dash: str, local_path: str) -> dict[str, Any]:
    """DIAGNOSTIK RE final: hapus file media OPFS (paksa re-download) + capture URL."""
    captured: list = []
    playwright_search.PLAYWRIGHT_ENABLED = True
    async with PlaywrightPool.get().semaphore:
        context = await XChatContextPool.get().acquire(auth_token)

        def _on_req(req):
            try:
                u = req.url
                if "abs.twimg.com" in u:
                    return
                if re.search(r"ton\.x\.com|xchat_media|/i/ton/|video\.twimg|/dm/|decrypt|media", u):
                    captured.append({"url": u, "method": req.method, "headers": dict(req.headers)})
            except Exception:
                pass

        context.on("request", _on_req)
        page = await context.new_page()
        try:
            await page.goto("https://x.com/i/chat", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            target = page
            cached = getattr(context, "_xchat_opfs_page", None)
            if cached is not None:
                try:
                    _ = cached.url; target = cached
                except Exception:
                    target = page
            del_js = """async (path) => {
                const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
                for(let i=0;i<10;i++){if(navigator.storage&&navigator.storage.getDirectory)break;await sleep(300);}
                if(!navigator.storage||!navigator.storage.getDirectory)return {error:'no api'};
                const parts=String(path).split('/').filter(Boolean);
                let dir=await navigator.storage.getDirectory();
                try {
                    for(let i=0;i<parts.length-1;i++) dir=await dir.getDirectoryHandle(parts[i]);
                    await dir.removeEntry(parts[parts.length-1]);
                    return {deleted:true};
                } catch(e){ return {deleted:false, error:String(e)}; }
            }"""
            delres = await target.evaluate(del_js, local_path)
            await page.goto(f"https://x.com/i/chat/{conv_dash}", wait_until="domcontentloaded", timeout=30000)
            await _ensure_pin_unlocked(page, dm_pin)
            for _ in range(10):
                await page.evaluate("""() => { for (const el of document.querySelectorAll('*')) {
                    const sr = el.shadowRoot; if (!sr) continue;
                    const sc = sr.querySelector('[data-testid="dm-message-scroller"]');
                    if (sc) { sc.scrollTop = sc.scrollHeight * Math.random(); sc.dispatchEvent(new Event('scroll')); } } }""")
                await asyncio.sleep(3)
            return {"delete_result": delres, "captured": captured[:50], "count": len(captured)}
        finally:
            try:
                context.remove_listener("request", _on_req)
            except Exception:
                pass
            cached = getattr(context, "_xchat_opfs_page", None)
            if page is not cached:
                await page.close()
            await XChatContextPool.get().release(auth_token, context)


_CRYPTO_HOOK_BODY = """
  if (globalThis.__mf_crypto_hooked) return 'already';
  globalThis.__mf_crypto_hooked = true;
  const log = globalThis.__mf_crypto_log = [];
  const cap = (o) => { if (log.length < 600) log.push(o); };
  const hex = (b, n) => { try { const u = new Uint8Array(b); let s=''; for (let i=0;i<Math.min(u.length,n);i++) s+=u[i].toString(16).padStart(2,'0'); return s; } catch(e){ return String(e); } };
  const blen = (b) => { try { return new Uint8Array(b).length; } catch(e){ return -1; } };
  const s = crypto.subtle;
  const wrap = (name) => {
    const orig = s[name].bind(s);
    s[name] = async function(...args) {
      const rec = {op:name, t:Date.now()};
      try {
        if (name==='importKey') {
          rec.format=args[0]; rec.algo=args[2];
          if (args[0]==='raw'||args[0]==='pkcs8'||args[0]==='spki') { rec.keyHex=hex(args[1],96); rec.keyLen=blen(args[1]); }
          if (args[0]==='jwk') { rec.jwk=args[1]; }
        } else if (name==='decrypt'||name==='encrypt') {
          rec.algo={name:args[0].name, iv:args[0].iv?hex(args[0].iv,32):null, tagLength:args[0].tagLength};
          rec.dataLen=blen(args[2]); rec.dataHex=hex(args[2],48);
        } else if (name==='digest') {
          rec.algo=args[0]; rec.dataLen=blen(args[1]); rec.dataHex=hex(args[1],160);
        } else if (name==='deriveBits') {
          rec.algo=args[0]; rec.bits=args[2];
        }
      } catch(e){ rec.err=String(e); }
      const out = await orig(...args);
      try {
        if (name==='decrypt'||name==='digest'||name==='deriveBits') { rec.outLen=blen(out); rec.outHex=hex(out,64); }
      } catch(e){}
      cap(rec);
      return out;
    };
  };
  ['importKey','decrypt','encrypt','digest','deriveBits'].forEach(wrap);
  return 'hooked';
"""
_CRYPTO_HOOK_JS = "() => {" + _CRYPTO_HOOK_BODY + "}"
# Init script: bungkus Worker klasik agar hook terpasang SEBELUM kode worker jalan.
_WORKER_HOOK_INIT = """
(() => {
  const body = %s;
  const OrigWorker = window.Worker;
  if (!OrigWorker || window.__mf_worker_wrapped) return;
  window.__mf_worker_wrapped = true;
  window.Worker = function(url, opts) {
    try {
      const u = String(url);
      if ((u.startsWith('blob:') || u.startsWith('data:') || !u.startsWith('http')) && (!opts || opts.type !== 'module')) {
        const wrapper = body + '\\n;importScripts("' + u + '");';
        const nb = new Blob([wrapper], {type: 'application/javascript'});
        return new OrigWorker(URL.createObjectURL(nb), opts);
      }
    } catch(e) {}
    return new OrigWorker(url, opts);
  };
  window.Worker.prototype = OrigWorker.prototype;
})();
""" % ("(() => {" + _CRYPTO_HOOK_BODY + "})()",)


async def debug_crypto_hook(auth_token: str, dm_pin: Optional[str], my_user_id: str,
                            conv_dash: str, entry_id: str) -> dict[str, Any]:
    """DIAGNOSTIK RE dinamis: hook crypto.subtle (page+worker), hapus file media
    OPFS entry terkait (paksa re-download+decrypt oleh client), kumpulkan trace
    key/iv/plaintext. Mengungkap skema dekripsi media tanpa RE statis penuh."""
    import sqlite3
    import tempfile
    captured: list = []
    playwright_search.PLAYWRIGHT_ENABLED = True
    async with PlaywrightPool.get().semaphore:
        context = await XChatContextPool.get().acquire(auth_token)
        try:
            await context.add_init_script(_WORKER_HOOK_INIT)
        except Exception:
            pass

        def _on_req(req):
            try:
                u = req.url
                if "ton.x.com" in u or "xchat_media" in u:
                    captured.append(u)
            except Exception:
                pass

        context.on("request", _on_req)
        page = await context.new_page()

        def _on_worker(w):
            try:
                asyncio.get_event_loop().create_task(w.evaluate(_CRYPTO_HOOK_JS))
            except Exception:
                pass

        page.on("worker", _on_worker)
        try:
            await page.goto("https://x.com/i/chat", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            await page.evaluate(_CRYPTO_HOOK_JS)
            for w in page.workers:
                try:
                    await w.evaluate(_CRYPTO_HOOK_JS)
                except Exception:
                    pass
            db_bytes = await extract_xchat_opfs_db(page, str(my_user_id), context=context, force=True)
            local_path = None
            att_rows: list = []
            if db_bytes and db_bytes[:15] == b"SQLite format 3":
                with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
                    tf.write(db_bytes); tmp = tf.name
                try:
                    conn = sqlite3.connect(tmp)
                    row = conn.execute(
                        "SELECT local_path FROM dm_local_attachment WHERE message_id = ?",
                        (entry_id,)).fetchone()
                    if row:
                        local_path = row[0]
                    cc = conv_dash.replace("-", ":")
                    for r in conn.execute(
                            "SELECT a.message_id, a.local_path, a.attachment_type, a.file_size "
                            "FROM dm_local_attachment a JOIN dm_entry e ON e.entry_id = a.message_id "
                            "WHERE e.conversation_id = ?", (cc,)):
                        att_rows.append({"message_id": r[0], "local_path": r[1],
                                         "type": r[2], "size": r[3]})
                    conn.close()
                finally:
                    os.unlink(tmp)
            delres = None
            if local_path:
                target = page
                cached = getattr(context, "_xchat_opfs_page", None)
                if cached is not None:
                    try:
                        _ = cached.url; target = cached
                        await target.evaluate(_CRYPTO_HOOK_JS)
                    except Exception:
                        target = page
                del_js = """async (path) => {
                    const parts=String(path).split('/').filter(Boolean);
                    let dir=await navigator.storage.getDirectory();
                    try {
                        for(let i=0;i<parts.length-1;i++) dir=await dir.getDirectoryHandle(parts[i]);
                        await dir.removeEntry(parts[parts.length-1]);
                        return {deleted:true};
                    } catch(e){ return {deleted:false, error:String(e)}; }
                }"""
                delres = await target.evaluate(del_js, local_path)
            await page.goto(f"https://x.com/i/chat/{conv_dash}", wait_until="domcontentloaded", timeout=30000)
            await _ensure_pin_unlocked(page, dm_pin)
            try:
                await page.evaluate(_CRYPTO_HOOK_JS)
            except Exception:
                pass
            for _ in range(6):
                try:
                    await page.evaluate("""() => { for (const el of document.querySelectorAll('*')) {
                        const sr = el.shadowRoot; if (!sr) continue;
                        const sc = sr.querySelector('[data-testid="dm-message-scroller"]');
                        if (sc) { sc.scrollTop = sc.scrollHeight * Math.random(); sc.dispatchEvent(new Event('scroll')); } } }""")
                except Exception:
                    pass
                await asyncio.sleep(2)
            logs = []
            try:
                logs.append({"src": "page", "log": await page.evaluate("globalThis.__mf_crypto_log || []")})
            except Exception as e:
                logs.append({"src": "page", "error": str(e)[:80]})
            for i, w in enumerate(page.workers):
                try:
                    logs.append({"src": f"worker{i}:{w.url[-60:]}", "log": await w.evaluate("globalThis.__mf_crypto_log || []")})
                except Exception as e:
                    logs.append({"src": f"worker{i}", "error": str(e)[:80]})
            exist_js = """async (paths) => {
                const out = [];
                for (const p of paths) {
                    const parts = String(p).split('/').filter(Boolean);
                    let dir = await navigator.storage.getDirectory();
                    try {
                        for (let i=0;i<parts.length-1;i++) dir = await dir.getDirectoryHandle(parts[i]);
                        const fh = await dir.getFileHandle(parts[parts.length-1]);
                        const f = await fh.getFile();
                        const buf = new Uint8Array(await f.slice(0,16).arrayBuffer());
                        let h=''; for (const b of buf) h+=b.toString(16).padStart(2,'0');
                        out.push({path:p, exists:true, size:f.size, magic:h});
                    } catch(e) { out.push({path:p, exists:false}); }
                }
                return out;
            }"""
            files_state = []
            if att_rows:
                try:
                    files_state = await page.evaluate(exist_js, [a["local_path"] for a in att_rows])
                except Exception as e:
                    files_state = [{"error": str(e)[:80]}]
            return {"local_path": local_path, "delete_result": delres,
                    "attachment_rows": att_rows, "files_state": files_state,
                    "media_urls": captured[:20], "crypto_logs": logs}
        finally:
            try:
                context.remove_listener("request", _on_req)
            except Exception:
                pass
            cached = getattr(context, "_xchat_opfs_page", None)
            if page is not cached:
                await page.close()
            await XChatContextPool.get().release(auth_token, context)


async def debug_context_request_capture(auth_token: str, dm_pin: Optional[str], conv_dash: str) -> dict[str, Any]:
    """DIAGNOSTIK RE deep: Playwright context.on('request') tangkap URL media
    lintas-page/worker (bypass encapsulation JS)."""
    captured: list = []
    playwright_search.PLAYWRIGHT_ENABLED = True
    async with PlaywrightPool.get().semaphore:
        context = await XChatContextPool.get().acquire(auth_token)

        def _on_req(req):
            try:
                u = req.url
                if "abs.twimg.com" in u:
                    return
                if re.search(r"ton\.x\.com|xchat_media|/i/ton/|video\.twimg|/dm/|decrypt|media", u):
                    captured.append({"url": u, "method": req.method,
                                     "headers": dict(req.headers)})
            except Exception:
                pass

        context.on("request", _on_req)
        page = await context.new_page()
        try:
            await page.goto(f"https://x.com/i/chat/{conv_dash}", wait_until="domcontentloaded", timeout=30000)
            await _ensure_pin_unlocked(page, dm_pin)
            for _ in range(8):
                await page.evaluate("""() => { for (const el of document.querySelectorAll('*')) {
                    const sr = el.shadowRoot; if (!sr) continue;
                    const sc = sr.querySelector('[data-testid="dm-message-scroller"]');
                    if (sc) { sc.scrollTop = sc.scrollHeight * Math.random(); sc.dispatchEvent(new Event('scroll')); } } }""")
                await asyncio.sleep(3)
            return {"captured": captured[:50], "count": len(captured)}
        finally:
            try:
                context.remove_listener("request", _on_req)
            except Exception:
                pass
            cached = getattr(context, "_xchat_opfs_page", None)
            if page is not cached:
                await page.close()
            await XChatContextPool.get().release(auth_token, context)


async def debug_entry_contents(auth_token: str, my_user_id: str, conv_dash: str,
                               entry_id: str) -> dict[str, Any]:
    """DIAGNOSTIK RE: dump contents BLOB entry (hex+strings) + ckey conv (hex)."""
    import sqlite3
    import tempfile
    playwright_search.PLAYWRIGHT_ENABLED = True
    async with PlaywrightPool.get().semaphore:
        context = await XChatContextPool.get().acquire(auth_token)
        page = await context.new_page()
        try:
            await page.goto("https://x.com/i/chat", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            db_bytes = await extract_xchat_opfs_db(page, str(my_user_id), context=context, force=True)
            if not db_bytes or db_bytes[:15] != b"SQLite format 3":
                return {"error": "no db"}
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
                tf.write(db_bytes); tmp = tf.name
            try:
                conn = sqlite3.connect(tmp)
                cc = conv_dash.replace("-", ":")
                row = conn.execute("SELECT contents FROM dm_entry WHERE entry_id = ?",
                                   (entry_id,)).fetchone()
                contents = row[0] if row else b""
                if isinstance(contents, str):
                    contents = contents.encode()
                strings = re.findall(rb"[\x20-\x7e]{4,}", contents or b"")
                ckeys = []
                for t, b in conn.execute(
                        "SELECT tag, bytes FROM dm_key_material WHERE tag LIKE ?",
                        ("ckey-" + cc + "-%",)):
                    ckeys.append({"tag": t, "hex": b.hex() if isinstance(b, (bytes, bytearray)) else str(b)})
                convrow = None
                try:
                    cols = [c[1] for c in conn.execute("PRAGMA table_info(dm_conversation)")]
                    cr = conn.execute("SELECT * FROM dm_conversation WHERE conversation_id = ?", (cc,)).fetchone()
                    if cr:
                        convrow = {c: (v.hex() if isinstance(v, (bytes, bytearray)) else v) for c, v in zip(cols, cr)}
                except Exception as e:
                    convrow = {"error": str(e)[:80]}
                conn.close()
                return {"contents_len": len(contents or b""),
                        "contents_hex": (contents or b"").hex(),
                        "strings": [s.decode() for s in strings][:60],
                        "ckeys": ckeys, "conv_row": convrow}
            finally:
                conn.close(); os.unlink(tmp)
        finally:
            cached = getattr(context, "_xchat_opfs_page", None)
            if page is not cached:
                await page.close()
            await XChatContextPool.get().release(auth_token, context)


async def debug_media_cdn_probe(auth_token: str, my_user_id: str, conv_dash: str) -> dict[str, Any]:
    """DIAGNOSTIK RE: ekstrak filename/media-id dari contents + uji CDN publik twimg."""
    import sqlite3
    import tempfile
    playwright_search.PLAYWRIGHT_ENABLED = True
    async with PlaywrightPool.get().semaphore:
        context = await XChatContextPool.get().acquire(auth_token)
        page = await context.new_page()
        try:
            await page.goto("https://x.com/i/chat", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            db_bytes = await extract_xchat_opfs_db(page, str(my_user_id), context=context, force=True)
            if not db_bytes or db_bytes[:15] != b"SQLite format 3":
                return {"error": "no db"}
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
                tf.write(db_bytes); tmp = tf.name
            try:
                conn = sqlite3.connect(tmp)
                cc = conv_dash.replace("-", ":")
                rows = conn.execute(
                    "SELECT entry_id, contents, attachment_types FROM dm_entry WHERE conversation_id=? AND has_attachment=1 AND deleted=0 ORDER BY timestamp DESC LIMIT 8",
                    (cc,)).fetchall()
            finally:
                conn.close(); os.unlink(tmp)
            found = []
            for r in rows:
                contents = r[1] or b""
                fnames = re.findall(rb"([A-Za-z0-9_\-]{8,}\.[a-z]{3,4})", contents)
                media_ids = re.findall(rb"(\d{15,20})", contents)
                found.append({"entry": r[0], "types": r[2],
                              "filenames": [f.decode() for f in fnames][:5],
                              "media_ids": [m.decode() for m in media_ids][:5]})
            # uji CDN publik utk filename pertama & media_id pertama
            tests = []
            for f in found:
                for fn in f["filenames"][:2]:
                    for label, u, hdrs in [
                        ("pbs_noauth", f"https://pbs.twimg.com/media/{fn}", {}),
                        ("pbs_cookie", f"https://pbs.twimg.com/media/{fn}", {"Cookie": "auth_token=" + auth_token}),
                    ]:
                        try:
                            rq = urllib.request.Request(u, headers=hdrs)
                            resp = urllib.request.urlopen(rq, timeout=20)
                            buf = resp.read()
                            tests.append({"label": label, "url": u, "status": resp.status,
                                          "bytes": len(buf), "magic": buf[:8].hex()})
                        except urllib.error.HTTPError as e:
                            tests.append({"label": label, "url": u, "status": e.code})
                        except Exception as e:
                            tests.append({"label": label, "url": u, "error": str(e)[:60]})
            return {"found": found, "cdn_tests": tests}
        finally:
            cached = getattr(context, "_xchat_opfs_page", None)
            if page is not cached:
                await page.close()
            await XChatContextPool.get().release(auth_token, context)


async def debug_key_material(auth_token: str, my_user_id: str, conv_dash: str,
                             tag_like: str = "") -> dict[str, Any]:
    """DIAGNOSTIK RE crypto: dump tabel kunci OPFS (schema + sample).
    tag_like: filter dm_key_material.tag (LIKE), dump hex penuh max 30 baris."""
    import sqlite3
    import tempfile
    playwright_search.PLAYWRIGHT_ENABLED = True
    async with PlaywrightPool.get().semaphore:
        context = await XChatContextPool.get().acquire(auth_token)
        page = await context.new_page()
        try:
            await page.goto("https://x.com/i/chat", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            db_bytes = await extract_xchat_opfs_db(page, str(my_user_id), context=context, force=True)
            if not db_bytes or db_bytes[:15] != b"SQLite format 3":
                return {"error": "no db"}
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
                tf.write(db_bytes); tmp = tf.name
            try:
                conn = sqlite3.connect(tmp)
                out = {}
                cc = conv_dash.replace("-", ":")
                for t in ["dm_key_material", "dm_my_keypair_versions", "dm_public_key_cache",
                          "dm_conversation_key_versions", "dm_pmk_bundle"]:
                    try:
                        cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})")]
                        cnt = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        rows = conn.execute(f"SELECT * FROM {t} LIMIT 2").fetchall()
                        sample = []
                        for r in rows:
                            rd = {}
                            for c, v in zip(cols, r):
                                if isinstance(v, (bytes, bytearray)):
                                    rd[c] = f"<bytes {len(v)}: {v[:16].hex()}>"
                                else:
                                    rd[c] = str(v)[:60]
                            sample.append(rd)
                        out[t] = {"cols": cols, "count": cnt, "sample": sample}
                    except Exception as e:
                        out[t] = {"error": str(e)[:60]}
                if tag_like:
                    rows = conn.execute(
                        "SELECT tag, bytes FROM dm_key_material WHERE tag LIKE ? LIMIT 30",
                        (tag_like,)).fetchall()
                    out["tag_matches"] = [
                        {"tag": t, "len": len(b) if isinstance(b, (bytes, bytearray)) else None,
                         "hex": b.hex() if isinstance(b, (bytes, bytearray)) else str(b)}
                        for t, b in rows]
                import re as _re
                from collections import Counter
                pats = Counter()
                for (t,) in conn.execute("SELECT tag FROM dm_key_material"):
                    pats[_re.sub(r"\d+", "N", str(t))] += 1
                out["tag_patterns"] = dict(pats.most_common(30))
                try:
                    rows = conn.execute(
                        "SELECT entry_id, timestamp, sender_id, has_attachment, attachment_types, deleted "
                        "FROM dm_entry WHERE conversation_id = ? ORDER BY timestamp DESC LIMIT 10",
                        (cc,)).fetchall()
                    out["conv_entries"] = [dict(zip(
                        ["entry_id","timestamp","sender_id","has_attachment","attachment_types","deleted"], r))
                        for r in rows]
                except Exception as e:
                    out["conv_entries"] = {"error": str(e)[:80]}
                try:
                    cnt = conn.execute("SELECT COUNT(*) FROM dm_local_attachment").fetchone()[0]
                    rows = conn.execute(
                        "SELECT message_id, local_path, attachment_type FROM dm_local_attachment "
                        "WHERE local_path LIKE ? LIMIT 10", ("%" + cc + "%",)).fetchall()
                    samp = conn.execute("SELECT message_id, local_path FROM dm_local_attachment LIMIT 3").fetchall()
                    out["attachments"] = {"total": cnt,
                        "conv_matches": [{"message_id": a, "local_path": b, "type": c} for a, b, c in rows],
                        "sample": [{"message_id": a, "local_path": b} for a, b in samp]}
                except Exception as e:
                    out["attachments"] = {"error": str(e)[:80]}
                try:
                    rows = conn.execute(
                        "SELECT * FROM dm_conversation_key_versions WHERE conversation_id = ?",
                        (cc,)).fetchall()
                    cols = [c[1] for c in conn.execute("PRAGMA table_info(dm_conversation_key_versions)")]
                    out["conv_key_versions"] = [dict(zip(cols, r)) for r in rows]
                except Exception as e:
                    out["conv_key_versions"] = {"error": str(e)[:60]}
                return out
            finally:
                conn.close(); os.unlink(tmp)
        finally:
            cached = getattr(context, "_xchat_opfs_page", None)
            if page is not cached:
                await page.close()
            await XChatContextPool.get().release(auth_token, context)


def query_dm_entries(
    conn: Any, conv_id_colon: str, limit: int = 50
) -> list[dict[str, Any]]:
    """Query baris dm_entry untuk satu percakapan (id format kolon),
    terbaru dulu."""
    rows = conn.execute(
        """
        SELECT entry_id, timestamp, sender_id, plain_text,
               has_attachment, message_status, deleted, event_type,
               attachment_types, contents
        FROM dm_entry
        WHERE conversation_id = ? AND deleted = 0
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (conv_id_colon, max(1, int(limit))),
    ).fetchall()
    cols = ["entry_id", "timestamp", "sender_id", "plain_text",
            "has_attachment", "message_status", "deleted", "event_type",
            "attachment_types", "contents"]
    return [dict(zip(cols, r)) for r in rows]


def query_inbox_rows(
    conn: Any, bot_user_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    """R88: daftar percakapan terbaru dari OPFS sqlite — pengganti scraper
    DOM inbox. Ambil dm_entry terbaru per conversation_id (plain_text jadi
    preview, timestamp jadi umur) lalu buang percakapan yang dm_conversation
    menandai deleted. Keluaran meniru unlock_and_read_xchat_inbox: id minus,
    conv_href, preview_text, relative_age_ms."""
    convs = conn.execute(
        """
        SELECT e.conversation_id AS cid,
               e.timestamp AS ts,
               e.plain_text AS preview,
               e.sender_id AS sender
        FROM dm_entry e
        JOIN (
            SELECT conversation_id, MAX(timestamp) AS max_ts
            FROM dm_entry
            WHERE deleted = 0 AND conversation_id IS NOT NULL
            GROUP BY conversation_id
        ) latest
          ON latest.conversation_id = e.conversation_id
         AND latest.max_ts = e.timestamp
        WHERE e.deleted = 0
        ORDER BY e.timestamp DESC
        LIMIT ?
        """,
        (max(1, int(limit)) * 2,),
    ).fetchall()
    now_ms = int(time.time() * 1000)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cid, ts, preview, sender in convs:
        if not cid or ":" not in cid or cid in seen:
            continue
        dash_id = cid.replace(":", "-")
        try:
            deleted_flag = conn.execute(
                "SELECT deleted FROM dm_conversation WHERE conversation_id = ?",
                (cid,),
            ).fetchone()
            if deleted_flag and deleted_flag[0]:
                continue
        except Exception:
            pass
        seen.add(cid)
        out.append({
            "id": dash_id,
            "conv_href": f"/i/chat/{dash_id}",
            "preview_text": (preview or "")[:120],
            "relative_age_ms": max(0, now_ms - (ts or now_ms)),
            "is_unread": False,
            "last_sender_id": str(sender or ""),
            "last_ts": ts,
        })
        if len(out) >= max(1, int(limit)):
            break
    return out


# R100: URL tweet yang dibagikan sender (attachment Post) tersimpan di contents
# BLOB, bukan plain_text. Ekstrak URL bersih (tanpa tracking ?a=&s= / garbage
# biner) agar bot meng-append-nya ke teks post sebagai quote card.
_POST_URL_RE = re.compile(
    rb"https?://(?:www\.)?(?:x\.com|twitter\.com)/[A-Za-z0-9_]+/status/\d+"
)


def _extract_post_links(contents: Any) -> list[str]:
    """R100: daftar URL tweet (x.com/twitter.com /status/) dari contents BLOB."""
    if not isinstance(contents, (bytes, bytearray)):
        return []
    out: list[str] = []
    for m in _POST_URL_RE.finditer(contents):
        url = m.group(0).decode("ascii")
        if url not in out:
            out.append(url)
    return out


def project_dm_entries_to_events(
    rows: list[dict[str, Any]], conversation_id: str
) -> list[dict[str, Any]]:
    """Baris dm_entry → event format Xapi (kompatibel dengan keluaran
    unlock_and_read_xchat_conversation)."""
    conv_dash = conversation_id.replace(":", "-")
    events: list[dict[str, Any]] = []
    for row in rows:
        entry_id = str(row.get("entry_id") or "")
        text = (row.get("plain_text") or "").strip()
        if not entry_id or not text:
            continue
        if row.get("deleted"):
            continue
        ts_ms = row.get("timestamp")
        created_at = None
        if isinstance(ts_ms, (int, float)) and ts_ms > 0:
            created_at = (
                datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            )
        event: dict[str, Any] = {
            "id": entry_id,
            "event_type": "MessageCreate",
            "dm_conversation_id": conv_dash,
            "sender_id": str(row.get("sender_id") or ""),
            "text": text,
            "created_at": created_at,
            "is_outgoing": str(row.get("sender_id") or "") == "" and False,
            "_xchat_decrypted": True,
            "_xchat_media_state": "none",
        }
        # R100: link tweet yang dibagikan (attachment Post) ada di contents,
        # bukan plain_text — ekstrak ke status_links agar ikut terposting.
        post_links = _extract_post_links(row.get("contents"))
        if post_links:
            event["status_links"] = post_links
        att_types = str(row.get("attachment_types") or "").lower()
        if row.get("has_attachment") and att_types == "media":
            # R90: lampiran media (foto/video) ditandai pending dulu;
            # recover_opfs_media_for_events membaca file terdekripsi dari
            # dm_local_attachment (OPFS) dan mengubahnya jadi ready bila
            # terpulihkan. R80 menjamin tenggat text-only bila tak lengkap.
            event["_xchat_media_pending"] = True
            event["_xchat_media_state"] = "pending"
        elif post_links:
            # R100: attachment link (Post tweet) bukan media yang perlu
            # diunduh — langsung post teks + link, jangan media-pending.
            event["_xchat_media_state"] = "none"
        events.append(event)
    events.reverse()  # kronologis
    return events


def _mime_from_opfs_path(path: str, attachment_type: Optional[str] = None) -> str:
    """Tebak MIME file media OPFS dari ekstensi local_path, lalu attachment_type.

    R94: video/GIF wajib dikenali benar (bukan jatuh ke foto) agar worker
    memprosesnya sebagai tweet_video/tweet_gif. attachment_type dipakai bila
    ekstensi tidak jelas (file OPFS kadang tanpa ekstensi)."""
    p = (path or "").lower()
    if p.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if p.endswith(".png"):
        return "image/png"
    if p.endswith(".webp"):
        return "image/webp"
    if p.endswith(".gif"):
        return "image/gif"
    if p.endswith(".mp4"):
        return "video/mp4"
    if p.endswith(".mov"):
        return "video/quicktime"
    at = (attachment_type or "").lower()
    if at.startswith("mediavideo"):
        return "video/mp4"
    if at.startswith("mediaanimatedgif") or at.startswith("mediagif"):
        return "image/gif"
    if at.startswith("mediaimage"):
        return "image/jpeg"
    return "image/jpeg"


async def recover_opfs_media_for_events(
    conn: Any,
    page: Any,
    context: Any,
    rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    max_files: int = 16,
) -> None:
    """R90: pulihkan media foto/video dari OPFS untuk event bertanda pending.

    `dm_local_attachment` memetakan message_id (= entry_id) → local_path file
    terdekripsi di OPFS. Baca bytes via read_xchat_opfs_file, cache sebagai
    attachment proxy (cache_e2ee_media). Set `_xapi_attachments` + state ready
    bila >= 1 lampiran terpulihkan. XChat headless jarang mengunduh media
    (download lazy saat render yang tak pernah terjadi), jadi menunggu SEMUA
    foto berarti text-only permanen via R80 — memposting media yang tersedia
    lebih baik daripada kehilangan semuanya. Bila 0 terpulihkan, biarkan
    pending (siklus berikut mencoba lagi; R80 menjamin tenggat text-only).
    Mutasi `events` in-place; bounded `max_files` bacaan per panggilan.
    """
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "dm_local_attachment" not in tables:
        return
    by_id = {str(r.get("entry_id") or ""): r for r in rows}
    reads = 0
    for ev in events:
        if not ev.get("_xchat_media_pending"):
            continue
        eid = str(ev.get("id") or "")
        # R91: jumlah lampiran yang DIHARAPKAN (attachmentId dalam contents).
        # Dipakai bot untuk memberi tahu pengirim bila recovery parsial.
        contents = (by_id.get(eid) or {}).get("contents")
        expected = (
            contents.count(b"attachmentId")
            if isinstance(contents, (bytes, bytearray)) else 0
        )
        if expected > 0:
            ev["_xchat_media_expected"] = expected
        try:
            cur = conn.execute(
                "SELECT * FROM dm_local_attachment WHERE message_id=?", (eid,))
            cols = [d[0] for d in cur.description]
            locals_ = [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            continue
        atts: list[dict[str, Any]] = []
        for la in locals_:
            if reads >= max_files:
                break
            lp = la.get("local_path")
            if not lp:
                continue
            raw = await read_xchat_opfs_file(page, lp, context=context)
            reads += 1
            if not raw:
                continue
            mime = _mime_from_opfs_path(lp, la.get("attachment_type"))
            kind = "video" if mime.startswith("video") else "photo"
            data_url = f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
            cached = cache_e2ee_media(
                data_url,
                key_hint=f"{eid}_{la.get('attachment_id') or reads}",
                kind=kind,
            )
            if cached:
                atts.append(cached)
        if atts:
            ev["_xapi_attachments"] = atts
            ev["attachments"] = {
                "media_keys": [
                    f"{'7' if a.get('kind') == 'video' else '3'}_{a['media_id']}"
                    for a in atts
                ]
            }
            ev["_xchat_media_state"] = "ready"
            ev["_xchat_media_recovered"] = len(atts)
            ev.pop("_xchat_media_pending", None)


def project_xchat_message_rows(
    rows_data: list[dict[str, Any]], conversation_id: str, max_results: int = 50,
) -> list[dict[str, Any]]:
    """Project browser rows into events, retaining unresolved-media state."""
    events: list[dict[str, Any]] = []
    for idx, row in enumerate(rows_data):
        ev_id = str(row.get("row_key") or f"{int(time.time() * 1000)}_{idx}")
        event: dict[str, Any] = {
            "id": ev_id,
            "event_type": "MessageCreate",
            "dm_conversation_id": conversation_id,
            "sender_id": row.get("sender_id"),
            "text": row.get("text"),
            "created_at": row.get("created_at"),
            "is_outgoing": bool(row.get("is_outgoing")),
            "_xchat_decrypted": True,
        }
        hrefs = row.get("hrefs") or []
        status_links = row.get("status_links") or []
        if hrefs:
            event["entities"] = {
                "urls": [{"url": u, "expanded_url": u, "display_url": u} for u in hrefs]
            }
        if status_links:
            event["status_links"] = status_links

        attachments = []
        for img_idx, data_url in enumerate(row.get("image_data_urls") or []):
            cached = cache_e2ee_media(
                data_url, key_hint=f"{conversation_id}_{ev_id}_{img_idx}"
            )
            if cached:
                attachments.append(cached)
        for video_idx, data_url in enumerate(row.get("video_data_urls") or []):
            cached = cache_e2ee_media(
                data_url,
                key_hint=f"{conversation_id}_{ev_id}_video_{video_idx}",
                kind="video",
                duration_ms=row.get("video_duration_ms"),
                width=row.get("video_width"),
                height=row.get("video_height"),
                thumbnail_data_url=(row.get("video_thumbnail_data_urls") or [None])[video_idx]
                if video_idx < len(row.get("video_thumbnail_data_urls") or []) else None,
            )
            if cached:
                attachments.append(cached)
        if attachments:
            event["_xapi_attachments"] = attachments
            event["attachments"] = {
                # Official X media-key prefixes: 3_ = photo, 7_ = video/GIF.
                "media_keys": [
                    f"{'7' if att.get('kind') == 'video' else '3'}_{att['media_id']}"
                    for att in attachments
                ]
            }
            event["_xchat_media_state"] = "ready"
        elif row.get("media_pending"):
            event["_xchat_media_pending"] = True
            event["_xchat_media_state"] = "pending"
        elif row.get("media_state") == "none":
            event["_xchat_media_state"] = "none"
        else:
            event["_xchat_media_pending"] = True
            event["_xchat_media_state"] = "pending"
        events.append({key: value for key, value in event.items() if value is not None})

    events.reverse()
    return events[:max_results]


async def unlock_and_read_xchat_conversation(
    auth_token: str,
    dm_pin: Optional[str],
    conversation_id: str,
    my_user_id: Optional[str] = None,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """
    Open https://x.com/i/chat/{conversation_id}, unlock PIN if needed, and extract
    decrypted messages, status links, and blob/ton.x.com images from the DOM.
    """
    norm_conv_id = conversation_id.replace(":", "-")
    peer_id = None
    if my_user_id and "-" in norm_conv_id:
        parts = norm_conv_id.split("-")
        peer_id = parts[1] if parts[0] == str(my_user_id) else parts[0]

    playwright_search.PLAYWRIGHT_ENABLED = True
    async with PlaywrightPool.get().semaphore:
        context = None
        page = None
        try:
            context = await XChatContextPool.get().acquire(auth_token)
            page = await context.new_page()
            # R85: goto percakapan dari page dingin memaksa X memuat chunk
            # ondemand XChatEmbed dari server — 27-79s, kadang tidak pernah
            # termuat (checked=0 berjam-jam). Warmup `/i/chat` SEKALI per
            # konteks memuat chunk ke cache HTTP: percakapan berikutnya
            # terbuka ~3s. Aman: host/sesi sama, tidak menyentuh percakapan.
            ctx_warmed = getattr(context, "_xchat_embed_warmed", False)
            if not ctx_warmed:
                try:
                    await page.goto(
                        "https://x.com/i/chat",
                        wait_until="domcontentloaded",
                        timeout=25000,
                    )
                    try:
                        await page.wait_for_function(
                            """() => {
                                window.__xchatHost = (() => {
                                    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
                                    if (legacy && legacy.shadowRoot) return legacy;
                                    // R86: DOM baru — embed me-render dm-* di dalam
                                    // shadow host GENERIK (tanpa testid). Cari host
                                    // mana pun yang shadowRoot-nya berisi elemen dm-.
                                    for (const el of document.querySelectorAll('*')) {
                                        const sr = el.shadowRoot;
                                        if (sr && sr.querySelector('[data-testid^="dm-"]')) {
                                            return el;
                                        }
                                    }
                                    return null;
                                })();
                                return !!window.__xchatHost;
                            }""",
                            timeout=15000,
                        )
                        context._xchat_embed_warmed = True
                    except Exception:
                        # Embed belum termuat — warmup tetap menghangatkan
                        # cache JS chunk; coba lagi nanti di fetch berikutnya.
                        pass
                except Exception as warm_exc:  # noqa: BLE001
                    log.debug("Warmup /i/chat gagal (dilanjutkan): %s", warm_exc)

            # R87: JALUR UTAMA BARU — baca SQLite OPFS (sinkron websocket,
            # plain_text terdekripsi). Halaman /i/chat cukup untuk mengaktifkan
            # sinkronisasi; tidak perlu menunggu baris DOM pernah dirender
            # (di headless, XChat baru TIDAK merender baris — hang 60-90s).
            if my_user_id:
                try:
                    db_bytes = await extract_xchat_opfs_db(page, str(my_user_id), context=context)
                    if db_bytes and db_bytes[:15] == b"SQLite format 3":
                        import sqlite3 as _sqlite3
                        import tempfile as _tempfile

                        with _tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
                            tf.write(db_bytes)
                            tmp_path = tf.name
                        conn = _sqlite3.connect(tmp_path)
                        try:
                            rows = query_dm_entries(
                                conn, norm_conv_id.replace("-", ":"), max_results
                            )
                            if rows:
                                events = project_dm_entries_to_events(
                                    rows, norm_conv_id
                                )
                                # R90: pulihkan media foto/video dari OPFS
                                # (dm_local_attachment) untuk event pending.
                                try:
                                    await recover_opfs_media_for_events(
                                        conn, page, context, rows, events
                                    )
                                except Exception as media_exc:  # noqa: BLE001
                                    log.debug(
                                        "R90: recovery media OPFS gagal (%s) — pending",
                                        media_exc,
                                    )
                                # R99: media masih pending = file belum terunduh
                                # ke OPFS. Baca OPFS saja tidak memicu unduhan;
                                # membuka halaman conv yang memicu client mengunduh
                                # media (terutama pesan terbaru). Kunjungi conv,
                                # tunggu sebentar, baca ulang db (force, bypass
                                # cache R95) dan recover lagi — supaya media tayang
                                # bersama menfess, bukan fallback teks setelah 45m.
                                if any(e.get("_xchat_media_pending") for e in events):
                                    try:
                                        await page.goto(
                                            f"https://x.com/i/chat/{norm_conv_id}",
                                            wait_until="domcontentloaded", timeout=25000,
                                        )
                                        await _ensure_pin_unlocked(page, dm_pin)
                                        await asyncio.sleep(_MEDIA_TRIGGER_WAIT_SEC)
                                        db2 = await extract_xchat_opfs_db(
                                            page, str(my_user_id), context=context, force=True
                                        )
                                        if db2 and db2[:15] == b"SQLite format 3":
                                            with _tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf2:
                                                tf2.write(db2)
                                                tmp2 = tf2.name
                                            conn2 = _sqlite3.connect(tmp2)
                                            try:
                                                rows2 = query_dm_entries(
                                                    conn2, norm_conv_id.replace("-", ":"), max_results
                                                )
                                                await recover_opfs_media_for_events(
                                                    conn2, page, context, rows2, events
                                                )
                                            finally:
                                                conn2.close()
                                                os.unlink(tmp2)
                                    except Exception as trig_exc:  # noqa: BLE001
                                        log.debug(
                                            "R99: trigger unduh media %s gagal (%s)",
                                            norm_conv_id, trig_exc,
                                        )
                                log.info(
                                    "R87: OPFS sqlite memulihkan %d event percakapan %s",
                                    len(events), norm_conv_id,
                                )
                                return events[:max_results]
                            log.debug(
                                "R87: OPFS sqlite kosong untuk %s — lanjut jalur DOM",
                                norm_conv_id,
                            )
                        finally:
                            conn.close()
                            os.unlink(tmp_path)
                except Exception as opfs_exc:  # noqa: BLE001
                    log.debug("R87: baca OPFS sqlite gagal (%s) — lanjut DOM", opfs_exc)

            url = f"https://x.com/i/chat/{norm_conv_id}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            unlocked = await _ensure_pin_unlocked(page, dm_pin)
            if not unlocked:
                return []

            # If PIN redirect sent us to /i/chat main list, navigate to the specific conversation
            if norm_conv_id not in page.url:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            # Guard anti salah-percakapan: setelah redirect PIN, URL WAJIB menunjuk
            # ke percakapan yang diminta. Kalau masih meleset (tab terbuka
            # percakapan lain), jangan baca apa pun — mencegah pesan dari
            # percakapan yang salah berpasangan ke placeholder inbox.
            for _gu in range(2):
                if norm_conv_id not in page.url:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(1.0)
            if norm_conv_id not in page.url:
                log.warning(
                    "unlock_and_read_xchat_conversation: URL tidak mengarah ke %s (actual: %s) — dibatalkan",
                    norm_conv_id, page.url,
                )
                return []

            # Wait for message rows to render
            try:
                await page.wait_for_function(
                    """() => {
                        const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                        const root = host?.shadowRoot || document;
                        return root.querySelectorAll('[data-dm-message-row], [data-testid^="message-text-"]').length > 0;
                    }""",
                    timeout=12000,
                )
            except Exception:
                await asyncio.sleep(2.0)

            # Wait for any images in the latest message rows to finish loading
            try:
                await page.wait_for_function(
                    """() => {
                        const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                        const root = host?.shadowRoot || document;
                        const rows = root.querySelectorAll('[data-dm-message-row]');
                        if (rows.length === 0) return true;
                        const tailRows = [...rows].slice(-2);
                        const imgs = tailRows.flatMap(r => [...r.querySelectorAll('img[src]')]).filter(
                            img => img.src.startsWith('blob:') || img.src.includes('ton.x.com') || img.src.includes('ton.twimg.com')
                        );
                        return imgs.length === 0 || imgs.every(img => img.complete && img.naturalWidth > 0);
                    }""",
                    timeout=5000,
                )
            except Exception:
                await asyncio.sleep(1.0)

            rows_data = await page.evaluate(
                """async ({convId, myId, peerId}) => {
                    const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                    const root = host?.shadowRoot || document;
                    // Virtualisasi XChat: baris lama (termasuk baris foto) hanya
                    // dimaterialisasi setelah di-scroll. Scroll dulu ke bawah-atas
                    // sebelum snapshot supaya lampiran pesan lama tidak hilang.
                    const sleep = (ms) => new Promise(r => setTimeout(r, ms));
                    const scroller = [...root.querySelectorAll('*')]
                        .filter(el => el.scrollHeight > el.clientHeight + 300)
                        .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0];
                    if (scroller) {
                        scroller.scrollTop = scroller.scrollHeight; await sleep(600);
                        let last = 0;
                        // Materialisasi penuh: baris virtual hanya muncul saat
                        // viewport menyentuh bagian tsb — jangkar di BAWAH lalu
                        // naik bertahap ke ATAS sambil menunggu render, sampai
                        // jumlah baris stabil. Tanpa ini, pesan ke-10+ hilang
                        // dari snapshot dan tak pernah diproses bot.
                        for (let i = 0; i < 14; i++) {
                            scroller.scrollTop = Math.max(0, scroller.scrollHeight - (i + 1) * (scroller.clientHeight * 1.2));
                            await sleep(320);
                            const n = root.querySelectorAll('[data-dm-message-row]').length;
                            if (n === last && n > 0 && i > 3) break;
                            last = n;
                        }
                        scroller.scrollTop = scroller.scrollHeight; await sleep(400);
                        scroller.scrollTop = 0; await sleep(400);
                    }
                    const rows = [...root.querySelectorAll('[data-dm-message-row]')];
                    const results = [];

                    const blobToDataUrl = async (src) => {
                        for (let attempt = 0; attempt < 3; attempt++) {
                            try {
                                const r = await fetch(src);
                                if (!r.ok) throw new Error(`media fetch ${r.status}`);
                                const blob = await r.blob();
                                const dataUrl = await new Promise((resolve) => {
                                    const reader = new FileReader();
                                    reader.onloadend = () => resolve(reader.result);
                                    reader.onerror = () => resolve(null);
                                    reader.readAsDataURL(blob);
                                });
                                if (dataUrl) return dataUrl;
                            } catch { /* retry transient blob/materialization failures */ }
                            if (attempt < 2) await sleep(300 * (attempt + 1));
                        }
                        return null;
                    };

                    for (let idx = 0; idx < rows.length; idx++) {
                        const row = rows[idx];
                        const rowKey = row.getAttribute('data-dm-message-row') || String(idx + 1);
                        const textNode = row.querySelector('[data-testid^="message-text-"]');
                        const text = textNode?.querySelector('[dir="auto"]')?.innerText?.trim()
                            || textNode?.innerText?.trim()
                            || null;
                        const senderLabel = row.querySelector('[id$="-sender"]')?.textContent?.trim() || '';
                        const sides = [...row.querySelectorAll('[data-side]')].map(el => el.getAttribute('data-side'));
                        const hasEndBubble = Boolean(
                            row.querySelector(
                                '[data-dm-message-focus-target$=":content"] [data-side="end"], ' +
                                '[data-dm-message-focus-target$=":attachment"] [data-side="end"]'
                            )
                        );
                        const isOutgoing = ['Anda', 'You'].includes(senderLabel) || hasEndBubble || sides.includes('end');
                        const hasAttachmentFocus = Boolean(row.querySelector('[data-dm-message-focus-target$=":attachment"]'));
                        const hasContentFocus = Boolean(row.querySelector('[data-dm-message-focus-target$=":content"]'));
                        const timeEl = row.querySelector('time[datetime]');
                        const createdAt = timeEl ? timeEl.getAttribute('datetime') : null;
                        const hrefs = [...new Set([...row.querySelectorAll('a[href]')].map(a => a.href).filter(Boolean))];
                        const statusLinks = hrefs.filter(h => /\\/status\\/\\d+/.test(h));

                        // Attachment focus can appear before its image/blob URL.
                        // Wait briefly per row; never silently downgrade a known
                        // attachment to a text-only event.
                        const videoEls = [...row.querySelectorAll('video')];
                        const mediaSrc = (src) => src && (
                            src.startsWith('blob:') || src.startsWith('data:') ||
                            src.includes('ton.x.com') || src.includes('ton.twimg.com') ||
                            src.includes('video.twimg.com')
                        );
                        let videoSources = [];
                        let videoPosterSources = [];
                        // XChat may attach the <video> node before metadata/source is
                        // ready. Poll briefly so a transient empty src/duration does
                        // not become a permanent text-only decision.
                        for (let wait = 0; videoEls.length > 0 && wait < 5; wait++) {
                            videoSources = [...new Set(videoEls.flatMap(v => [
                                v.currentSrc, v.src,
                                ...[...v.querySelectorAll('source')].map(s => s.src),
                            ].filter(mediaSrc)))];
                            videoPosterSources = [...new Set(videoEls.map(v =>
                                v.poster || v.getAttribute('data-poster') || v.getAttribute('poster')
                            ).filter(mediaSrc))];
                            const ready = videoEls.some(v =>
                                Number.isFinite(v.duration) && v.duration > 0 && videoSources.length > 0
                            );
                            if (ready) break;
                            await sleep(300);
                        }
                        const posterSet = new Set(videoPosterSources);
                        const attachmentRoot = row.querySelector('[data-dm-message-focus-target$=":attachment"]');
                        const imageSource = (img) => img.currentSrc || img.src ||
                            img.getAttribute('data-src') || img.getAttribute('data-image-url') || '';
                        const relevantImg = (img) => {
                            const src = imageSource(img);
                            if (!src || posterSet.has(src)) return false;
                            if (attachmentRoot && attachmentRoot.contains(img)) return true;
                            return src.startsWith('blob:') || src.includes('ton.x.com') ||
                                src.includes('ton.twimg.com') || src.includes('pbs.twimg.com');
                        };
                        let imgs = [...row.querySelectorAll('img')].filter(relevantImg);
                        for (let wait = 0; hasAttachmentFocus && imgs.length === 0 && wait < 5; wait++) {
                            await sleep(300);
                            imgs = [...row.querySelectorAll('img')].filter(relevantImg);
                        }
                        const imageDataUrls = [];
                        for (const img of imgs.slice(0, 4)) {
                            const dataUrl = await blobToDataUrl(imageSource(img));
                            if (dataUrl) imageDataUrls.push(dataUrl);
                        }
                        const videoDataUrls = [];
                        const videoThumbnailDataUrls = [];
                        let videoDurationMs = null;
                        let videoWidth = null;
                        let videoHeight = null;
                        let videoPending = false;
                        for (const video of videoEls.slice(0, 1)) {
                            const duration = Number.isFinite(video.duration) && video.duration > 0
                                ? video.duration : null;
                            videoDurationMs = duration != null ? Math.round(duration * 1000) : null;
                            videoWidth = video.videoWidth || null;
                            videoHeight = video.videoHeight || null;
                            if (videoSources.length === 0 || videoDurationMs == null) videoPending = true;
                        }
                        for (const src of videoSources.slice(0, 1)) {
                            const dataUrl = await blobToDataUrl(src);
                            if (dataUrl) videoDataUrls.push(dataUrl);
                            else videoPending = true;
                        }
                        for (const src of videoPosterSources.slice(0, 1)) {
                            const dataUrl = await blobToDataUrl(src);
                            if (dataUrl) videoThumbnailDataUrls.push(dataUrl);
                        }

                        // Skip completely empty divider/date rows, except a row
                        // explicitly exposing X's attachment focus target.
                        const hasAnyImg = imgs.length > 0;
                        const mediaPending = (hasAttachmentFocus || hasAnyImg) && imageDataUrls.length === 0;
                        const mediaReady = imageDataUrls.length > 0 || videoDataUrls.length > 0;
                        const mediaState = mediaReady ? 'ready' :
                            (videoPending || mediaPending ? 'pending' : (hasContentFocus && text ? 'none' : 'unknown'));
                        if (!text && imageDataUrls.length === 0 && statusLinks.length === 0
                            && !hasAnyImg && !hasAttachmentFocus && videoEls.length === 0) {
                            continue;
                        }

                        const curItem = {
                            row_key: rowKey,
                            text,
                            is_outgoing: isOutgoing,
                            sender_id: isOutgoing ? (myId || 'me') : (peerId || 'peer'),
                            created_at: createdAt,
                            hrefs,
                            status_links: statusLinks,
                            image_data_urls: imageDataUrls,
                            video_data_urls: videoDataUrls,
                            video_duration_ms: videoDurationMs,
                            video_width: videoWidth,
                            video_height: videoHeight,
                            video_thumbnail_data_urls: videoThumbnailDataUrls,
                            video_pending: videoPending,
                            media_pending: mediaPending || videoPending,
                            media_state: mediaState,
                            _has_attachment_only: hasAttachmentFocus && !hasContentFocus && !text,
                            _has_content_only: hasContentFocus && !hasAttachmentFocus && imageDataUrls.length === 0,
                        };

                        // Merge adjacent split rows (:content + :attachment) belonging to the same message
                        const prev = results.length > 0 ? results[results.length - 1] : null;
                        if (
                            prev &&
                            prev.is_outgoing === curItem.is_outgoing &&
                            ((prev._has_content_only && curItem._has_attachment_only) ||
                             (prev._has_attachment_only && curItem._has_content_only) ||
                             (!prev.text && curItem.text && prev.image_data_urls.length > 0 && curItem.image_data_urls.length === 0) ||
                             (prev.text && !curItem.text && prev.image_data_urls.length === 0 && curItem.image_data_urls.length > 0))
                        ) {
                            prev.text = prev.text || curItem.text;
                            prev.created_at = prev.created_at || curItem.created_at;
                            prev.hrefs = [...new Set([...prev.hrefs, ...curItem.hrefs])];
                            prev.status_links = [...new Set([...prev.status_links, ...curItem.status_links])];
                            prev.image_data_urls = [...prev.image_data_urls, ...curItem.image_data_urls].slice(0, 4);
                            prev.video_data_urls = [...(prev.video_data_urls || []), ...(curItem.video_data_urls || [])].slice(0, 1);
                            prev.video_duration_ms = prev.video_duration_ms || curItem.video_duration_ms;
                            prev.video_width = prev.video_width || curItem.video_width;
                            prev.video_height = prev.video_height || curItem.video_height;
                            prev.video_thumbnail_data_urls = [...(prev.video_thumbnail_data_urls || []), ...(curItem.video_thumbnail_data_urls || [])].slice(0, 1);
                            prev.video_pending = prev.video_pending || curItem.video_pending;
                            prev.media_pending = prev.media_pending || curItem.media_pending;
                            prev._has_attachment_only = false;
                            prev._has_content_only = false;
                            continue;
                        }

                        results.push(curItem);
                    }
                    return results;
                }""",
                {"convId": norm_conv_id, "myId": my_user_id, "peerId": peer_id},
            )

            return project_xchat_message_rows(
                rows_data or [], norm_conv_id, max_results=max_results
            )
        except Exception as exc:
            log.warning("unlock_and_read_xchat_conversation(%s) failed: %s", norm_conv_id, exc)
            return []
        finally:
            if page is not None:
                try:
                    cached_opfs = getattr(context, "_xchat_opfs_page", None) if context else None
                    if page is not cached_opfs:
                        await page.close()
                except Exception:
                    pass
            if context is not None:
                await XChatContextPool.get().release(auth_token, context)


async def send_xchat_dm_via_browser(
    auth_token: str,
    dm_pin: Optional[str],
    conversation_id: str,
    text: str,
) -> dict[str, Any]:
    """
    Send a DM message via XChat browser UI (/i/chat/{conversation_id}) when REST 1.1
    dm/new2.json is unavailable or conversation requires XChat E2EE.
    """
    norm_conv_id = conversation_id.replace(":", "-")
    playwright_search.PLAYWRIGHT_ENABLED = True
    async with PlaywrightPool.get().semaphore:
        context = None
        page = None
        try:
            context = await XChatContextPool.get().acquire(auth_token)
            page = await context.new_page()
            url = f"https://x.com/i/chat/{norm_conv_id}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            unlocked = await _ensure_pin_unlocked(page, dm_pin)
            if not unlocked:
                return {"status": "error", "error": "XChat PIN unlock failed"}

            if norm_conv_id not in page.url:
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            # Guard anti salah-percakapan: jangan kirim kalau URL tidak menunjuk
            # ke percakapan yang dituju (PIN redirect bisa mendarat di chat lain).
            for _gu in range(2):
                if norm_conv_id not in page.url:
                    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(1.0)
            if norm_conv_id not in page.url:
                return {"status": "error", "error": f"Browser tidak berada di percakapan {norm_conv_id}"}

            await page.wait_for_function(
                """(sel) => {
                    const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                    const root = host?.shadowRoot || document;
                    return Boolean(root.querySelector(sel));
                }""",
                arg=DM_COMPOSER_SELECTOR,
                timeout=15000,
            )

            prev_msg_count = await page.evaluate(
                """() => {
                    const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                    const root = host?.shadowRoot || document;
                    return root.querySelectorAll('[data-testid^="message-text-"]').length;
                }"""
            )

            inserted = await page.evaluate(
                """({sel, msg}) => {
                    const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                    const root = host?.shadowRoot || document;
                    const el = root.querySelector(sel);
                    if (!el) return false;
                    el.focus();
                    if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {
                        const proto = el.tagName === 'TEXTAREA'
                            ? window.HTMLTextAreaElement.prototype
                            : window.HTMLInputElement.prototype;
                        const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                        if (setter) setter.call(el, msg);
                        else el.value = msg;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                    return document.execCommand('insertText', false, msg);
                }""",
                {"sel": DM_COMPOSER_SELECTOR, "msg": text},
            )
            if not inserted:
                return {"status": "error", "error": "Could not insert text into XChat composer"}

            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")

            # Verify delivery: composer cleared OR message count grew
            delivered = False
            try:
                await page.wait_for_function(
                    """({sel, prevCount}) => {
                        const host = (() => {
    if (window.__xchatHost && window.__xchatHost.isConnected
        && (window.__xchatHost.shadowRoot || window.__xchatHost.querySelector('[data-testid^="dm-"]'))) {
        return window.__xchatHost;
    }
    const legacy = document.querySelector('[data-testid="xchatEmbedRoute"]');
    if (legacy && legacy.shadowRoot) { window.__xchatHost = legacy; return legacy; }
    for (const el of document.querySelectorAll('*')) {
        const sr = el.shadowRoot;
        if (sr && sr.querySelector('[data-testid^="dm-"]')) { window.__xchatHost = el; return el; }
    }
    return null;
})();
                        const root = host?.shadowRoot || document;
                        const el = root.querySelector(sel);
                        const val = el ? ((el.value ?? el.textContent) || '').trim() : '';
                        const curCount = root.querySelectorAll('[data-testid^="message-text-"]').length;
                        return val.length === 0 || curCount > prevCount;
                    }""",
                    arg={"sel": DM_COMPOSER_SELECTOR, "prevCount": prev_msg_count},
                    timeout=8000,
                )
                delivered = True
            except Exception:
                delivered = False

            if not delivered:
                return {"status": "error", "error": "XChat DM send not confirmed (composer still full and message count unchanged)"}

            await asyncio.sleep(0.5)
            return {
                "status": "ok",
                "data": {
                    "dm_conversation_id": norm_conv_id,
                    "dm_event_id": str(int(time.time() * 1000)),
                },
            }
        except Exception as exc:
            log.warning("send_xchat_dm_via_browser(%s) failed: %s", norm_conv_id, exc)
            return {"status": "error", "error": str(exc)}
        finally:
            if page is not None:
                try:
                    cached_opfs = getattr(context, "_xchat_opfs_page", None) if context else None
                    if page is not cached_opfs:
                        await page.close()
                except Exception:
                    pass
            if context is not None:
                await XChatContextPool.get().release(auth_token, context)
