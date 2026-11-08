# Xapi — X (Twitter) Cookie API

Mirror endpoint X API v2 (`docs.x.com/x-api`) lewat cookie `auth_token`. Backend: GraphQL & REST 1.1 via `curl_cffi` (Chrome TLS/JA3 impersonation + Anti-Detect) + Playwright fallback untuk endpoint CF-gated.

- **~120 routes** mirror v2 (read + write + DM/XChat + lists + media + community notes + trends)
- **Anti-Detect Engine** bawaan: profil browser deterministik per `auth_token` (`curl_cffi` Chrome 124/131/136 TLS JA3/JA4 + HTTP/2 frame + sinkronisasi `User-Agent`, `Sec-CH-UA`, `Sec-Fetch-*`, `x-client-transaction-id` HMAC, dan sticky proxy)
- **Full Direct Messages & XChat**: GraphQL DM/XChat (`GetInitialXChatPageQuery`, `GetConversationPageQuery`, `DmAllSearchSlice`, dll.) + dekoder binary Apache Thrift XChat + REST 1.1 merge + proxy download media DM (`ton.x.com`)
- **XChat E2EE via PIN** (`?dm_pin=`): buka `x.com/i/chat` headless, unlock PIN, pesan terdekripsi + gambar media E2EE tersimpan/sajikan — dengan **profil browser persist per akun** (unlock bertahan antar run)
- **Docs UI** built-in di `/` (interactive reference + try-it console)
- **OpenAPI/Swagger** di `/docs`
- **Agent Skill** di [`SKILL.md`](SKILL.md) — dipakai agent (Claude Code, opencode, dll) untuk memanggil API ini; katalog endpoint lengkap di [`references/`](references/)

## Setup

```bash
# 1. virtualenv (Python 3.9+ — pin requirements sudah py3.9-compatible;
#    di py>=3.10, versi lebih baru otomatis ter-install)
uv venv --python 3.11
source .venv/bin/activate

# 2. install deps
uv pip install -r requirements.txt

# 3. install Chromium untuk Playwright (sekali) — wajib untuk XChat E2EE
#    dan endpoint CF-gated
playwright install chromium
```

## Run

```bash
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Server jalan di `http://127.0.0.1:8000`.

| Path | Isi |
|---|---|
| `/` | Docs UI interaktif (Xapi reference + try-it) |
| `/docs` | Swagger UI bawaan FastAPI |
| `/info` | Service metadata JSON |
| `/login?auth_token=…` | Validasi cookie + return profile |
| `/2/...` | Mirror endpoint v2 |
| `/admin/stats` | Stats infra (locked behind `X-Admin-Token`) |

### Mode produksi (recommended)

```bash
# 1. Pre-compile docs UI bundle (esbuild → bundle.js, drop babel-standalone)
bash docs-ui/build.sh

# 2. Set env aman
export ALLOW_QUERY_AUTH=0           # reject ?auth_token= query (token bocor di access log)
export ENABLE_RAW=0                  # disable ?raw=1 (raw payload bocor cookie)
export ADMIN_TOKEN="$(openssl rand -hex 32)"
export ALLOWED_ORIGINS="https://yourdomain.com"

# 3. Run (workers=1 — caches per-worker; --no-access-log: uvicorn access log
#    mencantumkan query string penuh = bocor ?dm_pin=/?auth_token=; observability
#    cukup dari JSON access log bawaan yang path-only)
uvicorn main:app --host 0.0.0.0 --port 8000 --no-access-log
```

## Deploy VPS — systemd (auto-run saat boot)

File: [`deploy/xapi.service`](deploy/xapi.service) (unit systemd) +
[`deploy/deploy.sh`](deploy/deploy.sh) (update script idempotent).
Kedua file ini ada di repo — tinggal clone di VPS.

### 1. Dependensi sistem & user service

```bash
ssh user@vps-anda
sudo apt update && sudo apt install -y git python3-venv python3-pip curl
sudo useradd -r -m -d /opt/xapi -s /usr/sbin/nologin xapi
cd /opt/xapi
```

### 2. Clone + deploy otomatis (venv, deps, Chromium, .env)

```bash
sudo -u xapi git clone https://github.com/tianprtma/Xapi .
# repo privat: git clone https://<TOKEN_GITHUB>@github.com/tianprtma/Xapi .
sudo -u xapi bash deploy/deploy.sh
sudo -u xapi nano .env   # ADMIN_TOKEN, ALLOW_QUERY_AUTH=0, ENABLE_RAW=0,
                         # PLAYWRIGHT_ENABLED=1, PROXY_LIST= kosong/valid
```

### 3. Pasang unit & enable (auto-run saat boot + auto-restart saat crash)

```bash
sudo cp deploy/xapi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xapi
```

### 4. Verifikasi + unlock PIN pertama

```bash
systemctl status xapi --no-pager
curl -s http://127.0.0.1:8000/health
journalctl -u xapi -f                   # log JSON live

# Unlock PIN pertama (profil persist tersimpan di /opt/xapi/.xchat_profiles/)
curl -s -H "Authorization: Bearer $(grep -oP '(?<=^TEST_AUTH_TOKEN=).{40}' /opt/xapi/.env)"      -H "X-DM-Pin: 1234"      "http://127.0.0.1:8000/2/chat/conversations?max_results=5"
```

### 5. Bukti auto-run: reboot VPS

```bash
sudo reboot
# SSH lagi setelah naik:
systemctl status xapi --no-pager        # active (running) tanpa start manual = ✓
curl -s http://127.0.0.1:8000/health
```

### 6. Update rutin

```bash
sudo -u xapi bash /opt/xapi/deploy/deploy.sh   # git pull + deps + Chromium
sudo systemctl restart xapi
```

### Catatan VPS

- Unit bind `127.0.0.1:8000` — akses via SSH tunnel (`ssh -L 8000:127.0.0.1:8000 …`)
  atau nginx reverse proxy. `0.0.0.0` hanya jika wajib + firewall ketat.
- `Restart=always` + `RestartSec=5`: proses crash auto-hidup dalam 5 detik.
- `TimeoutStopSec=25`: budget shutdown agar flush storage unlock E2EE sempat jalan.
- Profil persist **terkunci** bila dipakai dua proses bersamaan (server + `fetch_dm_pin.py`
  di VPS yang sama) — jalankan salah satu, atau bedakan `XCHAT_PROFILE_DIR`.
- Bila Chromium komplain library OS kurang: `sudo playwright install-deps chromium`
  (atau `sudo .venv/bin/python -m playwright install-deps chromium`).

## Auth

Semua endpoint butuh `auth_token` cookie. Token di-pass via:

- **Header (preferred):** `Authorization: Bearer <auth_token>`
- **Query param (deprecated):** `?auth_token=<auth_token>` — bocor di access log, set `ALLOW_QUERY_AUTH=0` di prod

### Cara dapat `auth_token`

1. Buka `x.com`, login normal di browser.
2. DevTools → Application → Cookies → `https://x.com`.
3. Copy nilai cookie `auth_token` (40 hex chars).

## Endpoints v2 (mirror docs.x.com)

### Read

| Method | Path | Engine | Note |
|---|---|---|---|
| GET | `/2/users/me` | curl_cffi | current user profile |
| GET | `/2/users/by/username/{username}` | curl_cffi | UserByScreenName |
| GET | `/2/users/by?usernames=` | curl_cffi | bulk by handle (max 100) |
| GET | `/2/users?ids=` | playwright | bulk by id (max 100) |
| GET | `/2/users/{id}` | playwright | UserByRestId (CF-gated) |
| GET | `/2/users/search?query=` | playwright | search users |
| GET | `/2/users/{id}/tweets` | curl_cffi | UserTweets |
| GET | `/2/users/{id}/tweets/replies` | playwright* | UserTweetsAndReplies |
| GET | `/2/users/{id}/mentions` | playwright | SearchTimeline @handle |
| GET | `/2/users/{id}/media` | curl_cffi | UserMedia |
| GET | `/2/users/{id}/liked_tweets` | curl_cffi | Likes |
| GET | `/2/users/{id}/followers` | playwright* | Followers |
| GET | `/2/users/{id}/following` | curl_cffi | Following |
| GET | `/2/users/{id}/blocking` | curl_cffi | own blocking list |
| GET | `/2/users/{id}/muting` | curl_cffi | own muting list |
| GET | `/2/users/{id}/affiliates` | playwright | affiliations / highlights |
| GET | `/2/users/reposts_of_me` | playwright | search nativeretweets |
| GET | `/2/users/{id}/timelines/reverse_chronological` | curl_cffi | HomeLatestTimeline |
| GET | `/2/home_timeline` | curl_cffi | HomeTimeline (For You) |
| GET | `/2/tweets?ids=` | curl_cffi | bulk lookup (max 100) |
| GET | `/2/tweets/{id}` | curl_cffi | TweetResultByRestId |
| GET | `/2/tweets/{id}/detail` | curl_cffi | TweetDetail + replies |
| GET | `/2/tweets/{id}/liking_users` | curl_cffi | Favoriters |
| GET | `/2/tweets/{id}/retweeted_by` | curl_cffi | Retweeters |
| GET | `/2/tweets/{id}/quote_tweets` | playwright | SearchTimeline (`quoted_tweet_id:`) |
| GET | `/2/tweets/search/recent?query=` | playwright | SearchTimeline |
| GET | `/2/lists/{id}` | curl_cffi | ListByRestId |
| GET | `/2/lists/{id}/tweets` | curl_cffi | ListLatestTweetsTimeline |
| GET | `/2/lists/{id}/members` | curl_cffi | ListMembers |
| GET | `/2/lists/{id}/followers` | curl_cffi | ListSubscribers |
| GET | `/2/users/{id}/owned_lists` | curl_cffi | ListsManagementPageTimeline |
| GET | `/2/users/{id}/list_memberships` | curl_cffi | ListMemberships |
| GET | `/2/users/{id}/pinned_lists` | curl_cffi | PinnedTimelines |
| GET | `/2/users/{id}/bookmarks` | curl_cffi | Bookmarks (own only) |
| GET | `/2/users/{id}/bookmarks/folders` | curl_cffi | BookmarkFoldersSlice |
| GET | `/2/users/{id}/bookmarks/folders/{folder_id}` | curl_cffi | BookmarkFolderTimeline |
| GET | `/2/communities/{id}` | curl_cffi | CommunityByRestId |
| GET | `/2/notes/search/notes_written?alias=` | curl_cffi | Birdwatch contributor notes |
| GET | `/2/notes/search/posts_eligible_for_notes?tweet_id=` | curl_cffi | Birdwatch BatSignal |
| GET | `/2/trends?woeid=` / `/2/trends/by/woeid/{woeid}` | REST 1.1 | trends/place.json |
| GET | `/2/dm_events` | GraphQL + DM | GetInitialXChatPageQuery / GetInboxPageRequestQuery + fallback |
| GET | `/2/dm_events/search?query=` | GraphQL | DmAllSearchSlice / DmGroupSearchSlice / DmPeopleSearchSlice |
| GET | `/2/dm_events/{event_id}` | GraphQL + DM | GetMessageEventsPageQuery / GetInitialXChatPageQuery |
| GET | `/2/dm_conversations/{conversation_id}/dm_events` | GraphQL + DM | GetConversationPageQuery / GetMessageEventsPageQuery; `?dm_pin=` dekripsi E2EE |
| GET | `/2/dm_conversations/with/{participant_id}/dm_events` | GraphQL + DM | 1-on-1 DM events via GraphQL / REST fallback; `?dm_pin=` dekripsi E2EE |
| GET | `/2/dm_conversations/media/{dm_id}/{media_id}/{resource_id}` | DM Media | Proxy media DM: `dm_id` angka = `ton.x.com`; `dm_id=xchat` = cache E2EE in-memory |
| GET | `/2/chat/conversations` | GraphQL | XChat inbox conversations; `?dm_pin=` dekripsi preview E2EE |
| GET | `/2/chat/conversations/{conversation_id}/messages` | GraphQL | XChat conversation messages (alias `/events`) |
| GET | `/2/chat/requests` | GraphQL + DM | GetMessageRequestsPageQuery |
| GET | `/2/chat/permissions` | GraphQL | DmAvPermissionsQuery |
| GET | `/2/chat/public_keys?ids=` | GraphQL | GetPublicKeys |

\*Coba `curl_cffi` dulu, auto-fallback Playwright kalau CF block.

### Write

| Method | Path | Engine | Note |
|---|---|---|---|
| POST | `/2/tweets` | GraphQL | CreateTweet (text/reply/quote/media) |
| DELETE | `/2/tweets/{id}` | GraphQL | DeleteTweet |
| PUT | `/2/tweets/{id}/hidden` | GraphQL | ModerateTweet (hide reply) |
| POST | `/2/users/{id}/likes` | GraphQL | FavoriteTweet |
| DELETE | `/2/users/{id}/likes/{tweet_id}` | GraphQL | UnfavoriteTweet |
| POST | `/2/users/{id}/retweets` | GraphQL | CreateRetweet |
| DELETE | `/2/users/{id}/retweets/by/source_tweet_id/{tweet_id}` | GraphQL | DeleteRetweet |
| POST | `/2/users/{id}/bookmarks` | GraphQL | CreateBookmark |
| DELETE | `/2/users/{id}/bookmarks/{tweet_id}` | GraphQL | DeleteBookmark |
| POST | `/2/users/{id}/following` | REST 1.1 | follow user |
| DELETE | `/2/users/{src}/following/{tgt}` | REST 1.1 | unfollow |
| POST | `/2/users/{id}/muting` | REST 1.1 | mute |
| DELETE | `/2/users/{src}/muting/{tgt}` | REST 1.1 | unmute |
| POST | `/2/users/{id}/blocking` | REST 1.1 | block |
| DELETE | `/2/users/{src}/blocking/{tgt}` | REST 1.1 | unblock |
| POST | `/2/users/{id}/pinned_tweets` | GraphQL | PinTweet |
| DELETE | `/2/users/{id}/pinned_tweets/{tweet_id}` | GraphQL | UnpinTweet |
| POST | `/2/lists` | GraphQL | CreateList |
| PUT | `/2/lists/{id}` | GraphQL | UpdateList |
| DELETE | `/2/lists/{id}` | GraphQL | DeleteList |
| POST | `/2/lists/{id}/members` | GraphQL | ListAddMember |
| DELETE | `/2/lists/{id}/members/{user_id}` | GraphQL | ListRemoveMember |
| POST | `/2/users/{id}/followed_lists?list_id=` | GraphQL | ListSubscribe |
| DELETE | `/2/users/{id}/followed_lists/{list_id}` | GraphQL | ListUnsubscribe |
| POST | `/2/users/{id}/pinned_lists` | GraphQL | PinTimeline |
| DELETE | `/2/users/{id}/pinned_lists/{list_id}` | GraphQL | UnpinTimeline |
| POST | `/2/dm_conversations` | DM | create group/1-on-1 conv |
| POST | `/2/dm_conversations/with/{participant_id}/messages` | DM | send DM (by user) |
| POST | `/2/dm_conversations/{id}/messages` | DM | send DM (by conv) |
| POST | `/2/dm_conversations/{conversation_id}/accept` | DM | approve/accept DM request (by conv) |
| POST | `/2/dm_conversations/with/{participant_id}/accept` | DM | approve/accept DM request (by user) |
| DELETE | `/2/dm_conversations/{conversation_id}` | DM | reject/delete DM request or conversation |
| DELETE | `/2/dm_conversations/with/{participant_id}` | DM | reject/delete 1-on-1 DM request or conv |
| DELETE | `/2/dm_events/{event_id}` | DM | delete own message |
| POST | `/2/users/{id}/dm/block` | DM | block from DM |
| POST | `/2/users/{id}/dm/unblock` | DM | unblock from DM |
| POST | `/2/media/upload` | REST 1.1 chunked | upload image/video/gif |
| POST | `/2/media/metadata` | REST 1.1 | alt-text |
| POST | `/2/notes` | GraphQL | submit Birdwatch note |
| POST | `/2/evaluate_note` | GraphQL | rate Birdwatch note |
| DELETE | `/2/notes/{id}` | GraphQL | delete Birdwatch note |

### Query param umum

| Param | Default | Note |
|---|---|---|
| `max_results` | 20 | 1-100 |
| `pagination_token` | — | cursor (`meta.next_token` di response sebelumnya) |
| `raw` | 0 | `1` = bypass formatter v2, return raw GraphQL/REST payload (disable di prod via `ENABLE_RAW=0`) |

## Format response (X API v2 style)

Single resource:
```json
{
  "data": {
    "id": "44196397",
    "name": "Elon Musk",
    "username": "elonmusk",
    "verified": true,
    "public_metrics": {
      "followers_count": 239909925,
      "following_count": 1332,
      "tweet_count": 102601
    }
  }
}
```

Collection:
```json
{
  "data": [
    { "id": "...", "text": "...", "author_id": "...", "public_metrics": { "like_count": 0 } }
  ],
  "includes": { "users": [...], "media": [...], "tweets": [...] },
  "meta": { "result_count": 20, "next_token": "..." }
}
```

Error (RFC 7807 problem+json):
```json
{
  "errors": [
    { "title": "Not Found", "detail": "Tweet not found", "type": "not_found", "status": 404 }
  ]
}
```

## Contoh

```bash
TOKEN="your_auth_token_here"

# Current user
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/2/users/me

# User by handle
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/2/users/by/username/elonmusk

# User by ID (Playwright, ~2-3s)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/2/users/44196397

# Tweets
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/2/users/44196397/tweets?max_results=20"

# Search
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/2/tweets/search/recent?query=bitcoin&type=Latest"

# Direct Messages (GraphQL XChat + REST 1.1 merged, official v2 shape + media attachments)
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/2/dm_events?max_results=20"

# 1-on-1 DM history dengan user tertentu
curl -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/2/dm_conversations/with/44196397/dm_events"

# Download gambar/video dari DM (proxy ke ton.x.com dengan cookie auth_token)
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/2/dm_conversations/media/2040339972549656964/1786394285310038016/photo.jpg" \
  -o dm_photo.jpg
```

## XChat E2EE — ambil DM terenkripsi dengan PIN

DM XChat (`x.com/i/chat`) terenkripsi end-to-end. Xapi mengeksekusi alur resmi
X di headless Chromium (`PLAYWRIGHT_ENABLED=1` wajib): buka `/i/chat` → unlock
PIN → dekripsi dilakukan JS resmi X → plaintext + gambar dibaca dari DOM.

> **Keamanan PIN:** `?dm_pin=` di query string **bocor di access log uvicorn &
> reverse proxy** (terbukti saat audit 2026-11-08). Untuk produksi selalu pakai
> **header `X-DM-Pin: <pin>`** — didukung semua endpoint XChat. `?dm_pin=` hanya
> untuk dev/testing. Server (`python3 main.py`) sudah menjalankan uvicorn
> tanpa access log; bila menjalankan via CLI tambahkan `--no-access-log`.

```bash
# Inbox XChat (preview terdekripsi, unread, age) — header X-DM-Pin (produksi):
curl -H "Authorization: Bearer $TOKEN" -H "X-DM-Pin: 1234" \
  "http://127.0.0.1:8000/2/chat/conversations?max_results=20"

# Isi percakapan terdekripsi (pesans, attachments, status links)
curl -H "Authorization: Bearer $TOKEN" -H "X-DM-Pin: 1234" \
  "http://127.0.0.1:8000/2/dm_conversations/1394249284736864258-1831953836929638400/dm_events"

# Media DM biasa (proxy ton.x.com — full-res)
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/2/dm_conversations/media/2061680909850677279/2061680891307622401/aporq_o1.jpg" \
  -o dm_media.jpg

# Media XChat E2EE (dari cache proses server — jalankan flow conversation
# dengan dm_pin dulu; cache in-memory TTL 15 menit, gambar saja)
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/2/dm_conversations/media/xchat/{media_id}/img_{media_id}.jpg" \
  -o xchat_media.jpg
```

### Script standalone `fetch_dm_pin.py`

Tanpa perlu server — login + inbox REST/GraphQL + alur browser E2EE +
unduh media dalam satu proses (media langsung ke disk, tanpa cache endpoint):

```bash
# inbox E2EE terdekripsi
PROXY_LIST="" python3 fetch_dm_pin.py --pin 1234 --max 20

# scan media dari 19 percakapan pertama → simpan file ke ./media
PROXY_LIST="" python3 fetch_dm_pin.py --pin 1234 --save-media ./media --scan-limit 19

# 1 percakapan + simpan medianya
PROXY_LIST="" python3 fetch_dm_pin.py --pin 1234 \
  --conversation 1394249284736864258-1831953836929638400 --save-media ./media

# tanpa pin — pakai unlock tersimpan di profil persist (kalau masih valid)
PROXY_LIST="" python3 fetch_dm_pin.py --browser --save-media ./media
```

Catatan:
- **Profil persist per akun** (`XCHAT_PROFILE_DIR`, default `.xchat_profiles/`,
  di-gitignore): menyimpan cookie sesi + kunci E2EE → PIN tidak perlu diketik
  ulang setiap run. Namun gate PIN **dikontrol server X dan bisa muncul
  kembali sewaktu-waktu** — script menangani keduanya; siapkan `--pin`.
- Profil terkunci jika dipakai **dua proses bersamaan** (server + script) —
  jalankan salah satu dulu, atau set `XCHAT_PROFILE_DIR` berbeda.
- Hanya **gambar** yang terekstrak dari XChat (video belum didukung).

### Write contoh

```bash
TOKEN="your_auth_token_here"
ME="1391552089424158720"   # id auth user — dari /2/users/me
TARGET="44196397"           # id user target

# Create tweet
curl -X POST http://127.0.0.1:8000/2/tweets \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"halo dari Xapi"}'

# Reply
curl -X POST http://127.0.0.1:8000/2/tweets \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"@user reply","reply_to":"1234567890"}'

# Quote
curl -X POST http://127.0.0.1:8000/2/tweets \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"komen ya","quote_tweet_id":"1234567890"}'

# Tweet dengan gambar (upload dulu, ambil media_id)
MEDIA_ID=$(curl -s -X POST "http://127.0.0.1:8000/2/media/upload?media_type=image/jpeg" \
  -H "Authorization: Bearer $TOKEN" --data-binary @foto.jpg \
  | python -c "import json,sys; print(json.load(sys.stdin)['data']['media_id'])")

curl -X POST http://127.0.0.1:8000/2/tweets \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"text\":\"caption\",\"media_ids\":[\"$MEDIA_ID\"]}"

# Like / unlike
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"tweet_id\":\"1234567890\"}" \
  http://127.0.0.1:8000/2/users/$ME/likes

# Follow / unfollow
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"target_user_id\":\"$TARGET\"}" \
  http://127.0.0.1:8000/2/users/$ME/following

# Send DM
curl -X POST http://127.0.0.1:8000/2/dm_conversations/with/$TARGET/messages \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text":"halo dari xapi"}'
```

### Catatan write endpoint

- `media_ids` di `POST /2/tweets` boleh sampai 4 item.
- X kasih daily tweet limit; kalau ke-rate-limit balikin code `344`.
- Anti-bot X (CF) kadang block create tweet via cookie auth saja → code `226 AuthorizationError`. Solusi: jeda antar request, atau pakai akun yg sudah lama aktif.
- Upload video / GIF jalan lewat chunked + STATUS polling otomatis.

## Docs UI

Server-side mount: kunjungi `http://127.0.0.1:8000/`.

- Sidebar: 14 resource families (200 endpoint + 9 page).
- Endpoint page: params, responses, examples (cURL/JS/Python), try-it tab.
- Auto-detect `BASE_URL`:
  1. `window.XAPI_BASE_URL` (override via inline `<script>`)
  2. `?api=https://...` (query string, sticky di localStorage)
  3. `localStorage.xapi_base`
  4. `window.location.origin` (default — sama dengan API host)

### Build (production)

```bash
bash docs-ui/build.sh                 # esbuild → docs-ui/dist/bundle.js (~285KB minified)
```

`main.py` auto-detect `dist/` kalau ada → serve pre-compiled bundle (no Babel, hemat ~600KB load + parse). Tanpa `dist/`, fallback ke source files dengan in-browser Babel (development mode).

## Konfigurasi (env vars)

| Var | Default | Note |
|---|---|---|
| `ADMIN_TOKEN` | — | required header `X-Admin-Token` untuk `/admin/stats`. Kosong = endpoint hidden 404 |
| `ALLOW_QUERY_AUTH` | `1` | `0` = reject `?auth_token=` query (recommended di prod) |
| `ENABLE_RAW` | `1` | `0` = reject `?raw=1` query (recommended di prod) |
| `ALLOWED_ORIGINS` | — | CORS allowlist, comma-separated. Kosong = no CORS |
| `MAX_BODY_SIZE` | `1048576` | bytes (default 1 MB) untuk request body non-media |
| `MEDIA_UPLOAD_MAX_BYTES` | `52428800` | bytes (default 50 MB) untuk `/2/media/upload*` |
| `PROXY_LIST` | — | comma-separated proxy URLs (rotates per request) |
| `RESPONSE_CACHE_TTL` | `30` | seconds; `0` disables |
| `RETRY_MAX_ATTEMPTS` | `3` | upstream retry count |
| `CLIENT_POOL_MAX` | `50` | max pooled HTTP sessions |
| `CLIENT_POOL_TTL` | `600` | seconds (10 min) |
| `PLAYWRIGHT_MAX_CONCURRENT` | `4` | concurrent headless Chrome pages |
| `XCHAT_PROFILE_DIR` | `.xchat_profiles` | induk direktori profil persist XChat (cookie sesi + kunci E2EE di disk — lindungi!) |
| `XCHAT_PERSISTENT_MAX` | `3` | max profil/context persist aktif (LRU; evict aman — unlock state di disk) |
| `WEB_CONCURRENCY` | `1` | uvicorn workers. **Cache per-worker**, recommended `1` |

## Performance

- **Caches:** in-memory bounded LRU. SessionStore (5000 entries, 5 min TTL), ResponseCache (2000 entries, configurable TTL). Hit rate via `/admin/stats`.
- **Playwright:** browser di pre-warm di startup (~2-3s saved on first request). Concurrency cap `PLAYWRIGHT_MAX_CONCURRENT` (default 4) — di luar limit, antri.
- **XChat persistent profile:** satu browser process per akun (cap `XCHAT_PERSISTENT_MAX`, LRU idle di-evict). Evict/restart aman — unlock state di disk. Profil terkunci bila dua proses membuka akun yang sama bersamaan (WORKER=1).
- **Static asset:** `bundle.js` dapat 1-year immutable cache; `index.html` no-cache; lainnya 1-hour public.
- **Multi-worker:** caches tidak shared antar worker. Untuk scale-out, deploy multiple instances di belakang reverse proxy.

## Legacy endpoints

### `GET /login` — validasi & profile

```bash
# Bearer header (preferred)
curl http://127.0.0.1:8000/login -H "Authorization: Bearer YOUR_AUTH_TOKEN"

# Query (deprecated — akan reject kalau ALLOW_QUERY_AUTH=0)
curl "http://127.0.0.1:8000/login?auth_token=YOUR_AUTH_TOKEN"
```

Response:
```json
{
  "status": "valid",
  "http_status": 200,
  "user": {
    "id": "123456789",
    "screen_name": "username",
    "name": "Display Name",
    "verified": false,
    "public_metrics": { "followers_count": 100, "tweet_count": 1234 }
  }
}
```

### `POST /search` — search via Playwright

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{"auth_token":"YOUR_AUTH_TOKEN","q":"bitcoin","type":"Latest"}'
```

| Field | Type | Default | Note |
|---|---|---|---|
| `auth_token` | str | — | wajib |
| `q` | str | — | keyword |
| `type` | str | `Latest` | `Latest` \| `Top` \| `People` \| `Media` |

Lambat (~3-6 detik) tapi semua tipe jalan. Untuk app baru, pakai `GET /2/tweets/search/recent` dengan bearer header.

### `GET /admin/stats` — diagnostic (locked)

```bash
curl http://127.0.0.1:8000/admin/stats -H "X-Admin-Token: $ADMIN_TOKEN"
```

Return: session cache, TID provider, client pool, response cache (with hit/miss + hit_rate), v2 route inventory.

## Security & Anti-Detect

- **Deterministic Browser Fingerprinting (`BROWSER_PROFILES`):** Setiap `auth_token` dipetakan secara deterministik (`SHA-256`) ke satu profil perangkat tetap yang menyelaraskan:
  1. **TLS JA3/JA4 & HTTP/2 AKAMAI Fingerprint** via `curl_cffi` (`chrome124`, `chrome131`, `chrome136`)
  2. **`User-Agent`** yang persis cocok dengan versi Chrome & OS profil TLS
  3. **Client Hints (`Sec-CH-UA`, `Sec-CH-UA-Platform`, `Sec-CH-UA-Mobile`)** dan **Fetch Metadata (`Sec-Fetch-Dest`, `Sec-Fetch-Mode`, `Sec-Fetch-Site`, `Priority`)**
  4. **Sticky Proxy (`proxy_for_token`)**: Akun yang sama selalu keluar lewat proxy IP yang sama.
- **`x-client-transaction-id` (TID):** Dihasilkan secara lokal menggunakan HMAC + animasi key `ondemand.s` dari `x.com`. Bila masuk mode fallback, generator menghasilkan 70-byte random Base64 (94 karakter, tanpa prefix `fallback-`).
- **Playwright Stealth:** Context headless Chrome menginjeksi script inisialisasi untuk menyembunyikan `navigator.webdriver`, mengisi `window.chrome` & `navigator.plugins`, serta menyamakan `User-Agent` dan `Sec-CH-UA` dengan sesi `curl_cffi`.
- Bearer token publik web client X.com hardcoded — sama untuk semua user (extracted dari bundle x.com).
- `ct0` di-generate lokal (32 hex chars / 16 bytes sesuai standar X web), lalu di-sync dengan cookie `.x.com` dari server saat `warm_session`.
- Security headers default: HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, CSP.
- Body limit double-guard: `Content-Length` cek + stream-count untuk chunked TE.
- Admin token compare pakai `secrets.compare_digest` (constant-time).
- Username path: `^[A-Za-z0-9_]{1,15}$` enforce.
- Error message generic di production (full exception logged internal).
- `auth_token` validasi format `^[a-f0-9]{40}$` — reject sebelum upstream call.

Lihat [docs/audits/2026-05-17-security.md](docs/audits/) kalau ada (saat security review berikutnya).
