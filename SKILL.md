---
name: xapi
description: >-
  Use the Xapi server (X/Twitter cookie API mirroring X API v2) to read and write X data with a
  browser `auth_token` cookie instead of OAuth2. Covers users, tweets, timelines, search, lists,
  bookmarks, communities, Spaces, trends, DMs (including XChat E2EE-encrypted DMs via PIN), media
  upload/download, and Birdwatch notes. Use when the user asks to fetch, search, post, reply,
  quote, like, retweet, follow, bookmark, or DM on X/Twitter, or mentions Xapi, `auth_token`,
  `dm_pin`, `/2/tweets`, `/2/dm_events`, or a self-hosted X API.
---

# Xapi — X (Twitter) Cookie API

FastAPI mirror of X API v2 via cookie `auth_token`. Responses = official v2 shape.
Default base: `http://127.0.0.1:8000` (override `XAPI_BASE_URL`).

**Cara membaca:** seksi 🚀 dan 📋 cukup untuk 90% task. Detail panjang:
[references/endpoints.md](references/endpoints.md) (katalog) ·
[references/examples.md](references/examples.md) (snippet). Route hidup: `GET /openapi.json`.

```bash
B="$XAPI_BASE_URL"; H="Authorization: Bearer $XAPI_TOKEN"   # token 40 hex dari user/env — jangan reka
curl -s "$B/health"            # probe SEKALI di awal; sukses call pertama = tak perlu diulang
curl -s -H "$H" "$B/2/users/me"
```

## 🚀 Golden flows (1 tujuan = 1 perintah)

```bash
# Profilku / cari id user
curl -s -H "$H" "$B/2/users/me"                            # → data.id = "me"
curl -s -H "$H" "$B/2/users/by/username/elonmusk"          # → data.id

# Tweet user / 1 tweet / +balasan
curl -s -H "$H" "$B/2/users/44196397/tweets?max_results=20"
curl -s -H "$H" "$B/2/tweets/1234567890"
curl -s -H "$H" "$B/2/tweets/1234567890/detail"

# Keyword
curl -s -H "$H" "$B/2/tweets/search/recent?query=bitcoin&type=Latest"   # Latest|Top|Media|People

# DM: daftar percakapan / isi (tambah -H "X-DM-Pin: 1234" bila E2EE)
curl -s -H "$H" "$B/2/chat/conversations?max_results=20"
curl -s -H "$H" "$B/2/dm_conversations/111-222/dm_events"               # conv = "<peer>-<me>"

# Tulis: post / balas / quote
curl -s -X POST -H "$H" -H "Content-Type: application/json" -d '{"text":"hello"}' "$B/2/tweets"
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"text":"replying","reply_to":"1234567890"}' "$B/2/tweets"
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"text":"komentar","quote_tweet_id":"1234567890"}' "$B/2/tweets"

# Tulis: like / follow / kirim DM
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"tweet_id":"1234567890"}' "$B/2/users/$ME/likes"
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"target_user_id":"44196397"}' "$B/2/users/$ME/following"
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"text":"halo"}' "$B/2/dm_conversations/with/44196397/messages"

# Media: upload dulu → media_id → media_ids di POST /2/tweets (max 4)
MEDIA_ID=$(curl -s -X POST -H "$H" "$B/2/media/upload?media_type=image/jpeg" \
  --data-binary @foto.jpg | python3 -c "import json,sys; print(json.load(sys.stdin)['data']['media_id'])")
```

## 📋 Decision table (permintaan → endpoint)

| Permintaan | Endpoint | Catatan |
|---|---|---|
| siapa @handle / cari id | `GET /2/users/by/username/{handle}` | `data.id` dipakai untuk tulis |
| banyak handle sekaligus | `GET /2/users/by?usernames=a,b` | 1 call, max 100 |
| profil by id | `GET /2/users/{id}` | fallback cache/PW bila GraphQL gagal |
| tweet terbaru user | `GET /2/users/{id}/tweets` | `max_results` 1-100 |
| cari kata/tweet | `GET /2/tweets/search/recent?query=` | `type=Latest\|Top\|Media\|People` |
| 1 tweet / +balasan | `GET /2/tweets/{id}` / `/{id}/detail` | relasi di `referenced_tweets` |
| daftar DM | `GET /2/chat/conversations` (XChat) / `GET /2/dm_events` (v2) | E2EE: header `X-DM-Pin` |
| isi 1 percakapan | `GET /2/dm_conversations/{conv}/dm_events` | `?dm_pin=`/header bila E2EE |
| kirim DM | `POST /2/dm_conversations/with/{user_id}/messages` | body `{text}`; versi by-conv ada |
| post/balas/quote | `POST /2/tweets` | `text` + `reply_to`/`quote_tweet_id`/`media_ids` |
| like/unlike | `POST`·`DELETE /2/users/{me}/likes/{tweet_id}` | user_id = "me" |
| follow/unfollow | `POST/DELETE /2/users/{me}/following/{target}` | body `{target_user_id}` |
| upload media | `POST /2/media/upload?media_type=…` | body = bytes mentah |
| trending | `GET /2/trends/by/woeid/1` | 1=worldwide |
| lain (list/bookmark/note) | [endpoints.md](references/endpoints.md) | 501 = sengaja stub |

## ⚡ Speed cheat-sheet

- **1 probe per sesi**: `/health` di awal; call API pertama sukses → lanjut tanpa cek ulang.
- **Cache "me"**: `data.id` dari `/2/users/me` dipakai berulang — jangan login/resolve tiap task.
- **Resolve handle 1×**: id-sama disimpan; multi-id via `/2/users/by?usernames=`.
- **PIN hanya untuk DM E2EE**: jangan tanya `dm_pin` untuk tweet/lookup/follow. Tanya hanya saat
  respons DM kosong/gate, atau memang diminta.
- **Ekspektasi latensi** (sampaikan ke user): curl <1s · Playwright fallback 3-6s ·
  E2EE unlock 10-20s pertama. Lambat ≠ error.
- **Tulis = konfirmasi dulu, jangan retry agresif** (limit X: 344/226).
- **`?raw=1`** hanya debug; produksi bisa mati (`INFRA_RAW_DISABLED`).

## 🔑 Auth & respons

- Token via header; jangan `?auth_token=` (log leak).
- `{data}` / `{data, includes, meta:{result_count,next_token}}`; error branch di `errors[0].code`.
- `pagination_token` = `meta.next_token`. ID = string angka.

## 🛑 Error fast-fail

| Error code | Action |
|---|---|
| `AUTH_TOKEN_MISSING` / `AUTH_TOKEN_INVALID_FORMAT` | Berhenti — minta token 40-hex benar |
| `AUTH_TOKEN_EXPIRED` / `UPSTREAM_AUTH_REJECTED` | Token mati — user ambil ulang dari x.com |
| `RATE_LIMIT_EXCEEDED` | Tunggu `retry_after`; jangan paralel/hammer |
| `UPSTREAM_ERROR` (502) | Upstream bermasalah — retry 1×, lalu lapor |
| `STUB_NOT_IMPLEMENTED` (501) | Fitur tak tersedia — sampaikan, jangan janji |
| `not_found` (404) | Periksa id/username/respons sebelumnya |
| Gate PIN / DM E2EE kosong | Minta `dm_pin` user (4-8 digit) |

## 🔐 XChat E2EE (hanya bila DM terenkripsi)

- Dekripsi via Chromium server — `/health` harus `playwright: connected`
  (`PLAYWRIGHT_ENABLED=1` + Chromium terinstal).
- Produksi: PIN di **header** `X-DM-Pin: <pin>` — `?dm_pin=` bocor di log.
- Profil persist per akun (`.xchat_profiles/`) → unlock tak diulang; X tetap bisa re-gate.
- Extra fields: `_xchat_decrypted`, `is_outgoing`, `_xapi_attachments` (`proxy_path`), `status_links`.
  Media E2EE dari cache server (TTL 15m, gambar saja); DM biasa proxy `ton.x.com`.
- Tanpa server: `python3 fetch_dm_pin.py --pin 1234 [--save-media dir] [--conversation id]
  [--scan-limit N] [--browser]`.

## 🖥️ Server operations (ringkas — detail: README "Deploy VPS")

- Deploy/update VPS: `deploy/deploy.sh` (venv py3.11 + deps + Chromium) lalu
  `sudo bash deploy/install-service.sh [root]`; systemd auto-start.
- Diagnostik: `GET /admin/stats` (header `X-Admin-Token`; 404 bila tak diset).
- Satu akun = satu proses untuk profil XChat — jangan server + `fetch_dm_pin.py` barengan.

## ✍️ Write safety

Writes are real & public. Confirm before posting/deleting/following/blocking/DM kecuali
sudah diperintah eksplisit. Sebagian endpoint 501 (OAuth2-only) — cek
[endpoints.md](references/endpoints.md) sebelum menjanjikannya.