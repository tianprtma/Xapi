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
import secrets
import time
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
                    db_bytes = await extract_xchat_opfs_db(page, str(my_user_id))
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


async def extract_xchat_opfs_db(page: Any, viewer_id: str) -> Optional[bytes]:
    """Baca file SQLite OPFS `backups/chat_<viewer_id>.db` dari halaman X.
    Kembalikan bytes db, atau None bila file tidak ada."""
    b64 = await page.evaluate(_OPFS_DB_JS, f"chat_{viewer_id}.db")
    if not b64:
        return None
    try:
        import base64 as _b64
        return _b64.b64decode(b64)
    except Exception:
        return None


def query_dm_entries(
    conn: Any, conv_id_colon: str, limit: int = 50
) -> list[dict[str, Any]]:
    """Query baris dm_entry untuk satu percakapan (id format kolon),
    terbaru dulu."""
    rows = conn.execute(
        """
        SELECT entry_id, timestamp, sender_id, plain_text,
               has_attachment, message_status, deleted, event_type,
               attachment_types
        FROM dm_entry
        WHERE conversation_id = ? AND deleted = 0
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (conv_id_colon, max(1, int(limit))),
    ).fetchall()
    cols = ["entry_id", "timestamp", "sender_id", "plain_text",
            "has_attachment", "message_status", "deleted", "event_type",
            "attachment_types"]
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
        if row.get("has_attachment"):
            # Lampiran ada di db (contents BLOB / attachment_types) tapi media
            # bytes tidak tersedia dari jalur ini — tandai pending supaya jalur
            # media bot menanganinya (R80 menjamin tenggat text-only).
            event["_xchat_media_pending"] = True
            event["_xchat_media_state"] = "pending"
            event.pop("_xchat_media_state", None)
            event["_xchat_media_state"] = "pending"
        events.append(event)
    events.reverse()  # kronologis
    return events


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
                    db_bytes = await extract_xchat_opfs_db(page, str(my_user_id))
                    if db_bytes and db_bytes[:15] == b"SQLite format 3":
                        import sqlite3 as _sqlite3
                        import tempfile as _tempfile

                        with _tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
                            tf.write(db_bytes)
                            tmp_path = tf.name
                        try:
                            conn = _sqlite3.connect(tmp_path)
                            rows = query_dm_entries(
                                conn, norm_conv_id.replace("-", ":"), max_results
                            )
                        finally:
                            conn.close()
                            os.unlink(tmp_path)
                        if rows:
                            events = project_dm_entries_to_events(
                                rows, norm_conv_id
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
                    await page.close()
                except Exception:
                    pass
            if context is not None:
                await XChatContextPool.get().release(auth_token, context)
