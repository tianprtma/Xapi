#!/usr/bin/env python3
"""Search "tanyakanrl" → kumpulkan user → follow jika ≥50 followers & ≥50 following.

Batasan: max 100 follow/hari (counter disimpan di daily_counter.json).
Delay antar follow di-random 30-90s dengan occasional "istirahat" 3-8 menit
setiap 8-15 follow, meniru pola manusia.

Env vars (.env):
  XAPI_BASE_URL  — default http://127.0.0.1:8000
  AUTH_TOKEN     — X auth_token cookie (40 hex chars)
  SOURCE_USER_ID — user ID yang melakukan follow
  DRY_RUN        — 1 untuk skip follow
  TOP            — ambil N tweet teratas (default 50)
  MIN_FOLLOWERS  — default 50
  MIN_FOLLOWING  — default 50
  MAX_FOLLOW     — max follow per run (default 20)
  DAILY_LIMIT    — max follow/hari (default 100)
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ.get("XAPI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")
SOURCE_USER_ID = os.environ.get("SOURCE_USER_ID", "")
DRY_RUN = os.environ.get("DRY_RUN", "0") in ("1", "true", "yes")
TOP = int(os.environ.get("TOP", "50"))
MIN_FOLLOWERS = int(os.environ.get("MIN_FOLLOWERS", "50"))
MIN_FOLLOWING = int(os.environ.get("MIN_FOLLOWING", "50"))
MAX_FOLLOW = int(os.environ.get("MAX_FOLLOW", "20"))
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "100"))

COUNTER_FILE = Path(__file__).parent / "daily_counter.json"

if not AUTH_TOKEN or not SOURCE_USER_ID:
    print("ERROR: set AUTH_TOKEN dan SOURCE_USER_ID di .env", file=sys.stderr)
    sys.exit(1)


# ── daily counter ──

def _today() -> str:
    return date.today().isoformat()


def load_counter() -> dict:
    try:
        data = json.loads(COUNTER_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if data.get("date") != _today():
        return {"date": _today(), "followed": 0}
    return data


def save_counter(data: dict) -> None:
    COUNTER_FILE.write_text(json.dumps(data))


# ── human-like delay ──

def human_delay(label: str = "") -> float:
    """Return random delay in seconds, weighted toward realistic pauses."""
    r = random.random()
    if r < 0.6:
        s = random.uniform(30, 60)       # kebanyakan: 30-60s
    elif r < 0.85:
        s = random.uniform(60, 120)      # kadang: 1-2 menit
    else:
        s = random.uniform(15, 30)       # sesekali cepat
    if label:
        print(f"  ⏳ {label} {s:.0f}s...")
    return s


async def maybe_take_break(followed_this_session: int) -> None:
    """Setiap 8-15 follow, istirahat 3-8 menit."""
    if followed_this_session > 0 and followed_this_session % random.randint(8, 15) == 0:
        minutes = random.randint(3, 8)
        print(f"\n☕ Break {minutes} menit... ({datetime.now():%H:%M})")
        await asyncio.sleep(minutes * 60)


# ── API helpers ──

async def search_tweets(client: httpx.AsyncClient, query: str, top: int) -> dict[str, Any]:
    url = f"{BASE}/2/tweets/search/recent"
    params: dict[str, Any] = {
        "query": query,
        "max_results": min(top, 100),
        "type": "Latest",
        "auth_token": AUTH_TOKEN,
        "raw": 0,
    }
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def extract_users(tweets: list[dict], includes: list[dict]) -> dict[str, dict]:
    users: dict[str, dict] = {}
    for u in includes:
        uid = u.get("id")
        if uid:
            users[uid] = u
    for t in tweets:
        aid = t.get("author_id")
        if aid and aid not in users:
            users[aid] = {"id": aid, "username": "(unknown)"}
    return users


def qualifies(user: dict[str, Any]) -> bool:
    m = user.get("public_metrics", {}) or {}
    return (m.get("followers_count") or 0) >= MIN_FOLLOWERS and \
           (m.get("following_count") or 0) >= MIN_FOLLOWING


async def follow_user(client: httpx.AsyncClient, target_user_id: str) -> bool:
    url = f"{BASE}/2/users/{SOURCE_USER_ID}/following"
    params = {"auth_token": AUTH_TOKEN}
    body = {"target_user_id": target_user_id}
    try:
        resp = await client.post(url, json=body, params=params)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  ✗ gagal follow {target_user_id}: {e}", file=sys.stderr)
        return False


# ── main ──

async def main() -> None:
    counter = load_counter()
    remaining = DAILY_LIMIT - counter["followed"]
    effective_max = min(MAX_FOLLOW, remaining)

    print(f"📅 {counter['date']} | already followed: {counter['followed']}/{DAILY_LIMIT} "
          f"| remaining: {remaining} | max this run: {effective_max}")

    if remaining <= 0:
        print("🛑 Daily limit reached. Coba lagi besok.")
        return

    async with httpx.AsyncClient(timeout=30) as client:
        print(f"🔍 Search \"tanyakanrl\" (Latest, top={TOP})...")
        body = await search_tweets(client, "tanyakanrl", TOP)

        tweets = body.get("data", [])
        includes = body.get("includes", {}) or {}

        print(f"  Dapat {len(tweets)} tweets, {len(includes.get('users', []))} users di includes")

        users = extract_users(tweets, includes.get("users", []))
        qualified = [u for u in users.values() if qualifies(u)]
        qualified.sort(
            key=lambda u: (u.get("public_metrics", {}) or {}).get("followers_count", 0),
            reverse=True,
        )

        # Random shuffle untuk variasi — tidak selalu follow user teratas duluan
        random.shuffle(qualified)
        candidates = qualified[:effective_max]

        print(f"  Qualified: {len(qualified)} | Candidates this run: {len(candidates)}")

        if not candidates:
            print("🏁 Tidak ada kandidat baru.")
            return

        print(f"\n--- Candidates ---")
        for u in candidates:
            m = u.get("public_metrics", {}) or {}
            print(f"  @{u.get('username', '?')}  id={u['id']}  "
                  f"followers={m.get('followers_count', '?')}  "
                  f"following={m.get('following_count', '?')}")

        if DRY_RUN:
            print(f"\n🏁 DRY RUN — {len(candidates)} would be followed")
            return

        # Jeda awal acak (simulasi mikir)
        await asyncio.sleep(random.uniform(3, 8))

        followed = 0
        for i, u in enumerate(candidates):
            uname = u.get("username", u["id"])

            # Break detection untuk human pattern
            await maybe_take_break(followed)

            print(f"  → follow @{uname} ({u['id']})...", end=" ", flush=True)
            ok = await follow_user(client, u["id"])
            if ok:
                print("✓")
                followed += 1
                counter["followed"] += 1
                save_counter(counter)
            else:
                print("✗")

            # Jangan tidur setelah yang terakhir
            if i < len(candidates) - 1:
                remaining_after = remaining - followed
                if remaining_after <= 0:
                    print("🛑 Daily limit reached mid-run.")
                    break
                await asyncio.sleep(human_delay())

        print(f"\n✅ Done: {followed} followed | "
              f"total today: {counter['followed']}/{DAILY_LIMIT}")


if __name__ == "__main__":
    asyncio.run(main())
