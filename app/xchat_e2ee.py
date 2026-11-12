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


def cache_e2ee_media(data_url: str, key_hint: str = "") -> Optional[dict[str, str]]:
    """Store a base64 data URL from browser blob extraction into _E2EE_MEDIA_CACHE."""
    if not data_url or not data_url.startswith("data:"):
        return None
    try:
        header, b64_data = data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "").strip() or "image/png"
        raw_bytes = base64.b64decode(b64_data)
    except Exception:
        return None

    now = time.time()
    # Evict expired entries
    expired = [k for k, (_, _, ts) in _E2EE_MEDIA_CACHE.items() if now - ts > _E2EE_MEDIA_TTL]
    for k in expired:
        _E2EE_MEDIA_CACHE.pop(k, None)
    while len(_E2EE_MEDIA_CACHE) >= _E2EE_MEDIA_MAX:
        oldest_key = min(_E2EE_MEDIA_CACHE.items(), key=lambda kv: kv[1][2])[0]
        _E2EE_MEDIA_CACHE.pop(oldest_key, None)

    media_id = hashlib.sha256((key_hint or secrets.token_hex(8)).encode("utf-8") + raw_bytes[:256]).hexdigest()[:20]
    ext = (
        "jpg" if ("jpeg" in mime or "jpg" in mime)
        else ("webp" if "webp" in mime else ("gif" if "gif" in mime else "png"))
    )
    resource_id = f"img_{media_id}.{ext}"
    _E2EE_MEDIA_CACHE[media_id] = (raw_bytes, mime, now)

    return {
        "media_id": media_id,
        "kind": "photo",
        "url": f"https://ton.x.com/1.1/ton/data/dm/xchat/{media_id}/{resource_id}",
        "proxy_path": f"/2/dm_conversations/media/xchat/{media_id}/{resource_id}",
    }


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
                const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
        # inbox kosong. Konfirmasi stabil: kalau dalam settle window gate
        # PIN muncul (URL /pin/ atau 4 input), batal 'ready'.
        try:
            await asyncio.sleep(2.5)
            pin_check = await page.evaluate(
                """(pinSel) => {
                    const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
            elif not pin_check.get("links"):
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
                const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
            unlocked = await _ensure_pin_unlocked(page, dm_pin)
            if not unlocked:
                return []

            # Wait for conversation links to appear
            try:
                await page.wait_for_function(
                    """() => {
                        const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                        const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                        const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                        const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                        const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                        const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                    const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                        try {
                            const r = await fetch(src);
                            const blob = await r.blob();
                            return await new Promise((resolve) => {
                                const reader = new FileReader();
                                reader.onloadend = () => resolve(reader.result);
                                reader.onerror = () => resolve(null);
                                reader.readAsDataURL(blob);
                            });
                        } catch {
                            return null;
                        }
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

                        // Extract images from message rows (batas 4 per pesan; semua baris
                        // yang termaterialisasi, bukan hanya 6 baris terakhir)
                        const imageDataUrls = [];
                        if (true) {
                            const imgs = [...row.querySelectorAll('img[src]')].filter(
                                img => img.src.startsWith('blob:') || img.src.includes('ton.x.com') || img.src.includes('ton.twimg.com')
                            );
                            for (const img of imgs.slice(0, 4)) {
                                const dataUrl = await blobToDataUrl(img.src);
                                if (dataUrl) imageDataUrls.push(dataUrl);
                            }
                        }

                        // Skip completely empty divider/date rows
                        const hasAnyImg = row.querySelectorAll('img[src]').length > 0;
                        if (!text && imageDataUrls.length === 0 && statusLinks.length === 0 && !hasAnyImg) {
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

            events: list[dict[str, Any]] = []
            for idx, r in enumerate(rows_data or []):
                ev_id = str(r.get("row_key") or f"{ int(time.time() * 1000) }_{idx}")
                ev_obj: dict[str, Any] = {
                    "id": ev_id,
                    "event_type": "MessageCreate",
                    "dm_conversation_id": norm_conv_id,
                    "sender_id": r.get("sender_id"),
                    "text": r.get("text"),
                    "created_at": r.get("created_at"),
                    "is_outgoing": bool(r.get("is_outgoing")),
                    "_xchat_decrypted": True,
                }
                hrefs = r.get("hrefs") or []
                status_links = r.get("status_links") or []
                if hrefs:
                    ev_obj["entities"] = {
                        "urls": [{"url": u, "expanded_url": u, "display_url": u} for u in hrefs]
                    }
                if status_links:
                    ev_obj["status_links"] = status_links

                img_data_urls = r.get("image_data_urls") or []
                if img_data_urls:
                    atts = []
                    for i_idx, d_url in enumerate(img_data_urls):
                        cached = cache_e2ee_media(d_url, key_hint=f"{norm_conv_id}_{ev_id}_{i_idx}")
                        if cached:
                            atts.append(cached)
                    if atts:
                        ev_obj["_xapi_attachments"] = atts
                        ev_obj["attachments"] = {"media_keys": [f"3_{a['media_id']}" for a in atts]}

                events.append({k: v for k, v in ev_obj.items() if v is not None})

            # Return newest-first to match X API v2 dm_events ordering
            events.reverse()
            return events[:max_results]
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
                    const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
                    const root = host?.shadowRoot || document;
                    return Boolean(root.querySelector(sel));
                }""",
                arg=DM_COMPOSER_SELECTOR,
                timeout=15000,
            )

            prev_msg_count = await page.evaluate(
                """() => {
                    const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
                    const root = host?.shadowRoot || document;
                    return root.querySelectorAll('[data-testid^="message-text-"]').length;
                }"""
            )

            inserted = await page.evaluate(
                """({sel, msg}) => {
                    const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
                        const host = document.querySelector('[data-testid="xchatEmbedRoute"]');
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
