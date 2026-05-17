# Xapi — X (Twitter) Cookie API

Mirror endpoint X API v2 (`docs.x.com/x-api`) lewat cookie `auth_token`. Backend: GraphQL via httpx + Playwright fallback untuk endpoint CF-gated.

- **125 routes** mirror v2 (read + write + DM + lists + media + community notes + trends)
- **Docs UI** built-in di `/` (interactive reference + try-it console)
- **OpenAPI/Swagger** di `/docs`

## Setup

```bash
# 1. virtualenv (Python 3.11+)
uv venv --python 3.11
source .venv/bin/activate

# 2. install deps
uv pip install -r requirements.txt

# 3. install Chromium untuk Playwright (sekali)
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

# 3. Run (workers=1 — caches per-worker)
uvicorn main:app --host 0.0.0.0 --port 8000
```

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
| GET | `/2/users/me` | httpx | current user profile |
| GET | `/2/users/by/username/{username}` | httpx | UserByScreenName |
| GET | `/2/users/by?usernames=` | httpx | bulk by handle (max 100) |
| GET | `/2/users?ids=` | playwright | bulk by id (max 100) |
| GET | `/2/users/{id}` | playwright | UserByRestId (CF-gated) |
| GET | `/2/users/search?query=` | playwright | search users |
| GET | `/2/users/{id}/tweets` | httpx | UserTweets |
| GET | `/2/users/{id}/tweets/replies` | playwright* | UserTweetsAndReplies |
| GET | `/2/users/{id}/mentions` | playwright | SearchTimeline @handle |
| GET | `/2/users/{id}/media` | httpx | UserMedia |
| GET | `/2/users/{id}/liked_tweets` | httpx | Likes |
| GET | `/2/users/{id}/followers` | playwright* | Followers |
| GET | `/2/users/{id}/following` | httpx | Following |
| GET | `/2/users/{id}/blocking` | httpx | own blocking list |
| GET | `/2/users/{id}/muting` | httpx | own muting list |
| GET | `/2/users/reposts_of_me` | playwright | search nativeretweets |
| GET | `/2/users/{id}/timelines/reverse_chronological` | httpx | HomeLatestTimeline |
| GET | `/2/home_timeline` | httpx | HomeTimeline (For You) |
| GET | `/2/tweets?ids=` | httpx | bulk lookup (max 100) |
| GET | `/2/tweets/{id}` | httpx | TweetResultByRestId |
| GET | `/2/tweets/{id}/detail` | httpx | TweetDetail + replies |
| GET | `/2/tweets/{id}/liking_users` | httpx | Favoriters |
| GET | `/2/tweets/{id}/retweeted_by` | httpx | Retweeters |
| GET | `/2/tweets/{id}/quote_tweets` | playwright | SearchTimeline (`quoted_tweet_id:`) |
| GET | `/2/tweets/search/recent?query=` | playwright | SearchTimeline |
| GET | `/2/lists/{id}` | httpx | ListByRestId |
| GET | `/2/lists/{id}/tweets` | httpx | ListLatestTweetsTimeline |
| GET | `/2/lists/{id}/members` | httpx | ListMembers |
| GET | `/2/lists/{id}/followers` | httpx | ListSubscribers |
| GET | `/2/users/{id}/owned_lists` | httpx | ListsManagementPageTimeline |
| GET | `/2/users/{id}/list_memberships` | httpx | ListMemberships |
| GET | `/2/users/{id}/pinned_lists` | httpx | PinnedTimelines |
| GET | `/2/users/{id}/bookmarks` | httpx | Bookmarks (own only) |
| GET | `/2/users/{id}/bookmarks/folders` | httpx | BookmarkFoldersSlice |
| GET | `/2/users/{id}/bookmarks/folders/{folder_id}` | httpx | BookmarkFolderTimeline |
| GET | `/2/dm_events` | DM | inbox events |
| GET | `/2/dm_conversations/{id}/dm_events` | DM | conversation events |
| GET | `/2/dm_conversations/with/{participant_id}/dm_events` | DM | events with user |
| GET | `/2/dm_events/{event_id}` | DM | single event |
| GET | `/2/communities/{id}` | httpx | CommunityByRestId |
| GET | `/2/notes/search/notes_written?alias=` | httpx | Birdwatch contributor notes |
| GET | `/2/notes/search/posts_eligible_for_notes?tweet_id=` | httpx | Birdwatch BatSignal |
| GET | `/2/trends?woeid=` / `/2/trends/by/woeid/{woeid}` | REST 1.1 | trends/place.json |
| GET | `/2/users/personalized_trends` | REST 1.1 | personalized trends |

\*Coba httpx dulu, auto-fallback Playwright kalau CF block.

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
| POST | `/2/dm_conversations/with/{participant_id}/messages` | DM | send DM |
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
```

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

- Sidebar: 14 resource families (107 endpoint + 7 page).
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
| `WEB_CONCURRENCY` | `1` | uvicorn workers. **Cache per-worker**, recommended `1` |

## Performance

- **Caches:** in-memory bounded LRU. SessionStore (5000 entries, 5 min TTL), ResponseCache (2000 entries, configurable TTL). Hit rate via `/admin/stats`.
- **Playwright:** browser di pre-warm di startup (~2-3s saved on first request). Concurrency cap `PLAYWRIGHT_MAX_CONCURRENT` (default 4) — di luar limit, antri.
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

## Security

- Bearer token publik web client X.com hardcoded — sama untuk semua user (extracted dari bundle x.com).
- `ct0` di-generate lokal (random hex), di-sync dengan response server.
- API stateless — tiap request bikin session baru (di-cache 5 min).
- Security headers default: HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, CSP.
- Body limit double-guard: `Content-Length` cek + stream-count untuk chunked TE.
- Admin token compare pakai `secrets.compare_digest` (constant-time).
- Username path: `^[A-Za-z0-9_]{1,15}$` enforce.
- Error message generic di production (full exception logged internal).
- `auth_token` validasi format `^[a-f0-9]{40}$` — reject sebelum upstream call.

Lihat [docs/audits/2026-05-17-security.md](docs/audits/) kalau ada (saat security review berikutnya).
