# X API v2 Endpoint Coverage Audit

**Tanggal:** 2026-05-17 (revised setelah penghapusan endpoint Enterprise tier)
**Sumber spec:** `https://api.x.com/2/openapi.json` (161 endpoint resmi)
**File audit:** `main.py` v2.2.0

## TL;DR

- **Total v2 routes:** 116 (turun dari 172 — 56 endpoint Enterprise tier dihapus)
- **Implemented (real):** 88 — pakai GraphQL internal X / REST 1.1 via cookie auth
- **Stub 501:** 28 — return 501 untuk E2EE chat v2 + GraphQL op yang belum di-discover
- **Legacy routes:** 5 (di-keep untuk backwards-compat, ditandai `[LEGACY]` di docstring)

**Update batch terbaru (2026-05-17 sesi ke-3):** Semua endpoint X Enterprise tier di-hapus dari mirror — Streams (filtered/sample/firehose/label/likes), Compliance (jobs + streams), Webhooks (CRUD + replay + search webhooks), Account Activity API (legacy), Connections, Activity subscriptions, Search counts/all, Tweets analytics, Insights 28hr/historical, News, Media library/analytics/subtitles, Usage/tweets quota. Total 56 endpoint dihapus karena butuh OAuth2 app-only bearer + dev portal subscription yang tidak feasible dengan cookie-auth.

**Update batch sesi ke-2:** 13 endpoint baru di-impl via GraphQL internal — Lists subs/memberships/followers, Bookmark folders, ModerateTweet, CommunityByRestId, Birdwatch (notes/ratings/contributor slice/bat signal). queryId di-discover via Playwright + bundle scrape.

**Update DM batch (sesi sebelumnya):** 10 endpoint DM v2 di-impl via REST 1.1 internal X (`/i/api/1.1/dm/*`). Hanya `/2/chat/*` (E2EE) + `/2/dm_conversations/media/*` (signed URL flow) yang masih stub.

Beberapa endpoint resmi spec **tidak ada di mirror kita** (sengaja di-skip karena duplikatif): admin-only, deprecated experimental, atau redirect dari kanonikal yang sudah kita expose.

---

## 1. Implemented (88 — real)

### Users
- GET /2/users (bulk via fan-out UserByRestId)
- GET /2/users/by (bulk via fan-out UserByScreenName)
- GET /2/users/by/username/{username}
- GET /2/users/me
- GET /2/users/search (SearchTimeline product=People)
- GET /2/users/personalized_trends (REST 1.1)
- GET /2/users/reposts_of_me
- GET /2/users/{id}
- GET /2/users/{id}/followers
- GET /2/users/{id}/following
- GET /2/users/{id}/tweets
- GET /2/users/{id}/tweets/replies
- GET /2/users/{id}/liked_tweets
- GET /2/users/{id}/media
- GET /2/users/{id}/mentions
- GET /2/users/{id}/timelines/reverse_chronological
- GET /2/users/{id}/blocking
- GET /2/users/{id}/muting
- GET /2/users/{id}/bookmarks
- GET /2/users/{id}/owned_lists
- GET /2/users/{id}/pinned_lists
- POST /2/users/{id}/likes
- DELETE /2/users/{id}/likes/{tweet_id}
- POST /2/users/{id}/retweets
- DELETE /2/users/{user_id}/retweets/{tweet_id} (legacy)
- DELETE /2/users/{id}/retweets/by/source_tweet_id/{source_tweet_id} (canonical)
- POST /2/users/{id}/bookmarks
- DELETE /2/users/{id}/bookmarks/{tweet_id}
- POST /2/users/{id}/following
- DELETE /2/users/{source_user_id}/following/{target_user_id}
- POST /2/users/{id}/muting
- DELETE /2/users/{source_user_id}/muting/{target_user_id}
- POST /2/users/{id}/blocking (legacy, X v2 sudah deprecate POST blocking)
- DELETE /2/users/{source_user_id}/blocking/{target_user_id} (legacy)
- POST /2/users/{id}/pinned_tweets
- DELETE /2/users/{id}/pinned_tweets/{tweet_id}
- POST /2/users/{id}/pinned_lists (canonical)
- DELETE /2/users/{id}/pinned_lists/{list_id} (canonical)

### Tweets
- GET /2/tweets (bulk via fan-out)
- GET /2/tweets/{id}
- GET /2/tweets/{id}/detail
- GET /2/tweets/{id}/liking_users
- GET /2/tweets/{id}/retweeted_by
- GET /2/tweets/{id}/retweets (alias retweeted_by)
- GET /2/tweets/{id}/quote_tweets
- GET /2/tweets/search/recent
- POST /2/tweets
- DELETE /2/tweets/{id}

### Lists
- GET /2/lists/by/owner/{user_id} (legacy)
- GET /2/lists/{id}
- GET /2/lists/{id}/tweets
- GET /2/lists/{id}/members
- POST /2/lists
- DELETE /2/lists/{id}
- PUT /2/lists (legacy)
- PUT /2/lists/{id} (canonical)
- POST /2/lists/{id}/members
- DELETE /2/lists/{id}/members/{user_id}
- POST /2/lists/{id}/pinned (legacy)
- DELETE /2/lists/{id}/pinned (legacy)

### Misc
- GET /2/home_timeline
- GET /2/trends (legacy)
- GET /2/trends/by/woeid/{woeid} (canonical)
- POST /2/media/upload (chunked INIT/APPEND/FINALIZE internal)
- POST /2/media/metadata (alt_text via REST 1.1)

### Direct Messages (REST 1.1 internal — webapp x.com)
- GET /2/dm_events (dm/user_updates.json poll)
- GET /2/dm_events/{event_id} (scan inbox + filter)
- DELETE /2/dm_events/{event_id} (dm/destroy.json)
- GET /2/dm_conversations/with/{participant_id}/dm_events (dm/conversation/{me}-{other}.json)
- GET /2/dm_conversations/{conversation_id}/dm_events (dm/conversation/{conv}.json)
- POST /2/dm_conversations (group create — dm/new2.json auto-create)
- POST /2/dm_conversations/with/{participant_id}/messages (dm/new2.json 1-1)
- POST /2/dm_conversations/{conversation_id}/messages (dm/new2.json conv)
- POST /2/users/{user_id}/dm/block (dm/conversation/disable.json)
- POST /2/users/{user_id}/dm/unblock (dm/conversation/accept.json)

### GraphQL ops baru (batch 2026-05-17 sesi ke-2)
- PUT /2/tweets/{id}/hidden (op: ModerateTweet)
- GET /2/users/{id}/list_memberships (op: ListMemberships)
- POST /2/users/{id}/followed_lists?list_id=… (op: ListSubscribe)
- DELETE /2/users/{id}/followed_lists/{list_id} (op: ListUnsubscribe)
- GET /2/lists/{id}/followers (op: ListSubscribers)
- GET /2/users/{id}/bookmarks/folders (op: BookmarkFoldersSlice)
- GET /2/users/{id}/bookmarks/folders/{folder_id} (op: BookmarkFolderTimeline)
- GET /2/communities/{id} (op: CommunityByRestId)
- GET /2/notes/search/notes_written (op: BirdwatchFetchContributorNotesSlice)
- GET /2/notes/search/posts_eligible_for_notes (op: BirdwatchFetchBatSignal)
- POST /2/notes (op: BirdwatchCreateNote)
- DELETE /2/notes/{note_id} (op: BirdwatchDeleteNote)
- POST /2/evaluate_note (op: BirdwatchCreateRating)

---

## 2. Stub 501 (28) — by alasan

### Chat v2 E2EE (encrypted infra, butuh client-side key derivation)
- /2/chat/conversations (+ /group, /group/initialize, /keys, /members, /messages, /read, /typing)
- /2/chat/media/* (initialize/append/finalize)
- /2/chat/media/{id}/{hash}
- /2/dm_conversations/media/{dm_id}/{media_id}/{resource_id} (signed URL flow)

### GraphQL operation belum di-discover (queryId perlu trigger page-spesifik)
- GET /2/users/{id}/affiliates (op: UserAffiliatesTimeline — chunk lazy belum loaded)
- GET /2/users/{id}/followed_lists (op: ListSubscriptions — readlist mode beda dengan ListSubscribe)
- GET /2/spaces, /2/spaces/{id}, by/creator_ids, search, {id}/tweets (op: AudioSpace* — butuh /i/spaces page)
- GET /2/spaces/{id}/buyers (op: AudioSpaceBuyers — butuh OAuth2 user-context space owner)
- GET /2/communities/search (op: CommunitiesSearchSlideQuery — butuh /i/communities/explore)
- /2/users/public_keys, /2/users/{id}/public_keys (E2EE/PassKey infra — encrypted DM client)
- /2/media/upload/{initialize,append,finalize} (canonical aliases — gunakan POST /2/media/upload single-shot)

### Endpoint Enterprise tier yang di-hapus dari mirror (sesi ke-3)
Berikut endpoint yang dulu stub 501 dengan alasan Enterprise tier — sekarang **dihapus total** dari `main.py` karena tidak feasible dengan cookie-auth dan hanya bikin sidebar `/docs` jadi panjang:

- **Streams:** `/2/tweets/{sample|sample10|firehose|firehose/lang/*|label|compliance}/stream`, `/2/tweets/search/stream` (+ `/rules`, `/rules/counts`), `/2/likes/{firehose|sample10|compliance}/stream`, `/2/users/compliance/stream`, `/2/activity/stream`
- **Compliance:** `/2/compliance/jobs` (CRUD)
- **Webhooks:** `/2/webhooks` (CRUD + `/replay`), `/2/tweets/search/webhooks` (CRUD)
- **Account Activity:** `/2/account_activity/*` (legacy AA API), `/2/connections` (+ `/all`, `/{endpoint_id}`), `/2/activity/subscriptions` (CRUD)
- **Search counts/all:** `/2/tweets/counts/recent`, `/2/tweets/counts/all`, `/2/tweets/search/all`
- **Analytics/Insights:** `/2/tweets/analytics`, `/2/insights/28hr`, `/2/insights/historical`, `/2/media/analytics`
- **Media library:** `/2/media`, `/2/media/{key}`, `/2/media/subtitles` (POST/DELETE)
- **News:** `/2/news/search`, `/2/news/{id}`
- **Quota:** `/2/usage/tweets`

---

## 3. Tidak di-mirror (sengaja di-skip)

Beberapa path di spec resmi tidak dibuat karena:
- **Path duplikatif/alias** yang sudah di-cover oleh canonical lain
- **Admin/internal-only** endpoint yang tidak relevan untuk consumer

---

## 4. Pola request

Semua endpoint pakai auth yang sama:
- Header: `Authorization: Bearer <auth_token>`
- atau Query: `?auth_token=<auth_token>`
- Tambahkan `?raw=1` untuk dapat payload mentah X (bypass formatter v2)

Endpoint write yang butuh user-id konfirmasi (pin/like/retweet/dll) tetap memvalidasi format, tapi backend pakai user dari cookie — `user_id` di path harus = user current.

---

## 5. Cara meng-implement stub baru

### Untuk endpoint yang butuh GraphQL op baru
1. Buka bundle x.com di DevTools Network
2. Cari request `graphql/<queryId>/<OperationName>`
3. Salin: queryId, features, fieldToggles ke `_gql_meta.json`
4. Ganti body endpoint dari `_stub_501(...)` jadi:
   ```python
   result = await _graphql_call("<OperationName>", {...vars}, tok, method="POST")
   return _write_finalize(result, raw=bool(raw))
   ```

### Untuk endpoint enterprise
Tidak feasible tanpa subscription X Data API + bearer app-only.

### Untuk DM/Chat
Butuh OAuth2 user-context dengan scope `dm.read`/`dm.write`. Cookie web tidak setara — meski X internal punya REST 1.1 `dm/user_updates.json`, struktur respons berbeda dan kompleks.

---

## 6. Quick stats

| | Count |
|---|---:|
| Spec resmi (openapi.json) | 161 |
| Implemented (real) | 88 |
| Stub 501 (didefinisikan + 501) | 28 |
| Endpoint Enterprise di-hapus | 56 |
| **Total v2 routes di main.py** | **116** |
| Coverage real (relatif feasible scope) | **~76%** |
| Coverage real (relatif spec resmi) | **~55%** |
