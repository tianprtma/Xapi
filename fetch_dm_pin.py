#!/usr/bin/env python3
"""Ambil DM (termasuk XChat E2EE) memakai auth_token + DM PIN.

Standalone test script — memakai jalur produksi Xapi yang sama:
  - REST/GraphQL DM (tanpa browser) untuk inbox/pesan biasa
  - Playwright unlock PIN x.com/i/chat + pembacaan E2EE terdekripsi (dengan --pin)

Pemakaian:
    export TEST_AUTH_TOKEN=<40-hex auth_token cookie>   # atau --token
    python3 fetch_dm_pin.py --pin 123456                # inbox XChat (unlock E2EE)
    python3 fetch_dm_pin.py --pin 123456 --conversation 111-222
    python3 fetch_dm_pin.py                             # tanpa pin: REST/GraphQL saja

Output: JSON ke stdout (format sama dengan endpoint API):
    {data: [events...]}/{data: [conversations...]} + meta
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Muat .env SEBELUM import app.* (config membaca env saat import) —
# logika sama dengan main.py.
_ENV_FILE = Path(__file__).resolve().parent / ".env"
if _ENV_FILE.is_file():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.auth import api_headers, login_with_auth_token, resolve_me_id, warm_session  # noqa: E402
from app.client_pool import pooled_client  # noqa: E402
from app.clients import dm_call, graphql_call  # noqa: E402
from app.xchat_e2ee import (  # noqa: E402
    get_cached_e2ee_media,
    resolve_dm_pin,
    unlock_and_read_xchat_conversation,
    unlock_and_read_xchat_inbox,
)
from formatter import format_dm_events  # noqa: E402


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


_MIME_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
    "image/gif": "gif", "image/webp": "webp", "video/mp4": "mp4",
}


async def _download_ton(tok: str, url: str):
    """Unduh media ton.x.com memakai session ber-cookie (pola sama dengan
    proxy endpoint di app/routers/dm.py)."""
    async with pooled_client(tok) as client:
        ct0, _ = await warm_session(client, tok)
        hdrs = api_headers(ct0, tok)
        hdrs.pop("content-type", None)
        resp = await client.get(url, headers=hdrs)
        if resp.status_code == 200:
            return resp.content, (resp.headers.get("content-type") or "").lower()
        return None, f"HTTP {resp.status_code}"


async def _save_media(events, conv_id: str, out_dir: Path, tok: str) -> list[str]:
    """Tulis media dari event ke out_dir: byte E2EE dari cache proses, atau
    unduh ton.x.com untuk DM biasa. Return daftar path yang tersimpan."""
    saved = []
    for ev in events or []:
        for att in ev.get("_xapi_attachments") or []:
            if not isinstance(att, dict):
                continue
            mid = str(att.get("media_id") or "")
            url = att.get("url") or ""
            mime = (att.get("mime") or "").lower()
            kind = att.get("kind") or ""
            ext = _MIME_EXT.get(mime) or ("jpg" if kind == "photo" else "bin")
            fname = f"{conv_id}_{mid}.{ext}" if mid else f"{conv_id}_{len(saved)}.{ext}"

            data = None
            if mid:
                cached = get_cached_e2ee_media(mid)
                if cached:
                    data, cmime = cached
                    ext = _MIME_EXT.get((cmime or "").lower()) or ext
                    fname = f"{conv_id}_{mid}.{ext}" if mid else fname
            if data is None and url.startswith("http"):
                data, _ctype = await _download_ton(tok, url)
            if data:
                path = out_dir / fname
                path.write_bytes(data)
                saved.append(str(path))
    return saved


async def _inbox_via_api(tok: str) -> dict:
    """Inbox via jalur HTTP (GraphQL XChat + fallback REST 1.1)."""
    result = await graphql_call("GetInitialXChatPageQuery", {"count": 50}, tok)
    if not isinstance((result.get("data") or {}).get("data"), dict) or not (result.get("data") or {}).get("data"):
        result = await graphql_call("GetInboxPageRequestQuery", {"count": 50}, tok)
    if result.get("status") != "ok":
        rest = await dm_call("dm/user_updates.json", tok)
        if rest.get("status") == "ok":
            result = rest
    payload = result.get("data") or {}
    return format_dm_events(payload.get("data") if isinstance(payload.get("data"), dict) else payload)


async def main() -> int:
    ap = argparse.ArgumentParser(description="Ambil DM / XChat E2EE dengan PIN")
    ap.add_argument("--token", default=os.environ.get("TEST_AUTH_TOKEN", ""),
                    help="auth_token (40 hex). Default: env TEST_AUTH_TOKEN")
    ap.add_argument("--pin", default=os.environ.get("DM_PIN", ""),
                    help="DM PIN XChat 4-8 digit. Default: env DM_PIN")
    ap.add_argument("--conversation", default=None,
                    help="conversation_id (mis. 111-222). Kosong = inbox")
    ap.add_argument("--browser", action="store_true",
                    help="Paksa jalur browser XChat walau tanpa --pin "
                         "(pakai profil persist — unlock lama tetap berlaku)")
    ap.add_argument("--save-media", metavar="DIR", default=None,
                    help="Simpan file media DM ke direktori ini. Tanpa "
                         "--conversation = scan N percakapan pertama")
    ap.add_argument("--scan-limit", type=int, default=6,
                    help="Max percakapan di-scan cari media (default 6)")
    ap.add_argument("--max", type=int, default=50, help="max hasil (default 50)")
    args = ap.parse_args()

    tok = args.token.strip()
    if len(tok) != 40 or not all(c in "0123456789abcdef" for c in tok.lower()):
        print("ERROR: --token/TEST_AUTH_TOKEN kosong atau bukan 40-hex", file=sys.stderr)
        return 2
    pin = resolve_dm_pin(args.pin)

    # 1) Validasi token + profil (login flow, network via PROXY_LIST)
    login = await login_with_auth_token(tok)
    if login.get("status") != "valid":
        _emit({"step": "login", "status": login.get("status"), "error": login.get("error")})
        return 1
    me = (login.get("user") or {}).get("id")
    print(f"# login OK — user_id={me} screen_name={ (login.get('user') or {}).get('screen_name') }",
          file=sys.stderr)

    out_dir = Path(args.save_media) if args.save_media else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    if not args.conversation:
        # 2a) Jalur browser XChat: dengan pin (unlock) atau tanpa pin bila
        #     profil persist masih berisi unlock sebelumnya
        if pin or args.browser or out_dir:
            inbox = await unlock_and_read_xchat_inbox(tok, pin, my_user_id=me,
                                                      max_results=args.max)
            if out_dir:
                # Scan N percakapan pertama, simpan media yang ditemukan
                conv_ids = [c["id"] for c in inbox[:max(1, args.scan_limit)]]
                all_saved = []
                for cid in conv_ids:
                    events = await unlock_and_read_xchat_conversation(
                        tok, pin, cid, my_user_id=me, max_results=max(12, args.max))
                    saved = await _save_media(events, cid, out_dir, tok)
                    print(f"# {cid}: {len(saved)} media tersimpan", file=sys.stderr)
                    all_saved.extend(saved)
                _emit({"source": "media-scan", "scanned": conv_ids,
                       "saved_count": len(all_saved), "files": all_saved,
                       "dir": str(out_dir)})
                return 0
            _emit({"source": "xchat-e2ee-browser", "data": inbox,
                   "meta": {"result_count": len(inbox)}})
            return 0
        # 2b) Tanpa pin: jalur HTTP biasa
        out = await _inbox_via_api(tok)
        _emit({"source": "rest-graphql", **out})
        return 0

    # 3) Conversation tertentu
    conv_id = args.conversation.replace(":", "-")
    if pin:
        events = await unlock_and_read_xchat_conversation(
            tok, pin, conv_id, my_user_id=me, max_results=args.max)
        if out_dir:
            saved = await _save_media(events, conv_id, out_dir, tok)
            print(f"# {conv_id}: {len(saved)} media tersimpan", file=sys.stderr)
            _emit({"source": "media-save", "dm_conversation_id": conv_id,
                   "saved_count": len(saved), "files": saved, "dir": str(out_dir)})
        else:
            _emit({"source": "xchat-e2ee-browser", "dm_conversation_id": conv_id,
                   "data": events, "meta": {"result_count": len(events)}})
        return 0
    result = await graphql_call("GetConversationPageQuery", {
        "conversationId": conv_id.replace("-", ":"), "conversation_id": conv_id.replace("-", ":"),
        "count": args.max}, tok)
    payload = (result.get("data") or {}).get("data") or {}
    events = format_dm_events(payload, max_results=args.max).get("data") or []
    if out_dir:
        saved = await _save_media(events, conv_id, out_dir, tok)
        print(f"# {conv_id}: {len(saved)} media tersimpan", file=sys.stderr)
        _emit({"source": "media-save", "dm_conversation_id": conv_id,
               "saved_count": len(saved), "files": saved, "dir": str(out_dir)})
    else:
        out = format_dm_events(payload, max_results=args.max)
        _emit({"source": "rest-graphql", **out})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
