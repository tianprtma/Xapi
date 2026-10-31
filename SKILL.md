---
name: xapi
description: >-
  Use the Xapi server (X/Twitter cookie API mirroring X API v2) to read and write X data with a
  browser `auth_token` cookie instead of OAuth2. Covers users, tweets, timelines, search, lists,
  bookmarks, communities, Spaces, trends, DMs, media upload, and Birdwatch notes. Use when the
  user asks to fetch, search, post, reply, quote, like, retweet, follow, bookmark, or DM on
  X/Twitter, or mentions Xapi, `auth_token`, `/2/tweets`, or a self-hosted X API.
---

# Xapi — X (Twitter) Cookie API

Xapi is a FastAPI server that mirrors the X API v2 using a logged-in browser cookie
(`auth_token`) instead of OAuth2. Responses follow the X API v2 shape.

- Default base URL: `http://127.0.0.1:8000` (override with `XAPI_BASE_URL`)
- Full route list (source of truth): `GET /openapi.json`, Swagger at `/docs`, docs UI at `/`
- Detailed endpoint catalog: [references/endpoints.md](references/endpoints.md)
- Copy-paste examples: [references/examples.md](references/examples.md)

## Before calling the API

1. Confirm the server is reachable: `curl -s "$XAPI_BASE_URL/info"`.
2. Get the token from the user or env `XAPI_TOKEN` (40 lowercase hex chars, the `auth_token`
   cookie value from `x.com`). Never invent a token.
3. If the server is not running and you have this repo, start it:
   `uvicorn main:app --host 127.0.0.1 --port 8000` (see `README.md` for setup).

## Authentication

Always send the token in a header:

```bash
curl -s -H "Authorization: Bearer $XAPI_TOKEN" "$XAPI_BASE_URL/2/users/me"
```

- Never put the token in the URL (`?auth_token=`) unless the user explicitly asks; it leaks in
  access logs and may be disabled server-side (`AUTH_QUERY_DISABLED`).
- Never print, log, or commit the token. Redact it in command output you show the user.

Validate a token and get the current profile with `GET /login` or `GET /2/users/me`.

## Conventions

- **IDs are numeric strings.** Resolve a handle to an ID first:
  `GET /2/users/by/username/{username}` → `data.id`. Most write endpoints need the numeric ID.
- **Pagination:** pass `max_results` (1–100, default 20) and `pagination_token` from the previous
  response's `meta.next_token`.
- **Raw payloads:** add `?raw=1` only when debugging a formatter issue; it may be disabled
  (`INFRA_RAW_DISABLED`).
- **Read responses:** `{ "data": ..., "includes": {...}, "meta": { "result_count", "next_token" } }`.
- **Errors:** non-2xx returns `{ "errors": [ { "code", "title", "detail", "type", "status" } ] }`.
  Branch on `errors[0].code`, not on prose.
- **Own-resource endpoints** (bookmarks, blocking, muting, home timeline, liked tweets) only work
  for the authenticated user's own ID.

## Typical flows

```bash
B="$XAPI_BASE_URL"; H="Authorization: Bearer $XAPI_TOKEN"

# Me / resolve handle
curl -s -H "$H" "$B/2/users/me"
curl -s -H "$H" "$B/2/users/by/username/elonmusk"

# User tweets / search / detail
curl -s -H "$H" "$B/2/users/44196397/tweets?max_results=20"
curl -s -H "$H" "$B/2/tweets/search/recent?query=bitcoin&type=Latest"
curl -s -H "$H" "$B/2/tweets/1234567890/detail"

# Post, reply, quote
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"text":"hello from Xapi"}' "$B/2/tweets"
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"text":"replying","reply_to":"1234567890"}' "$B/2/tweets"

# Like / retweet / follow (user_id = your own ID from /2/users/me)
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"tweet_id":"1234567890"}' "$B/2/users/$ME/likes"
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"target_user_id":"44196397"}' "$B/2/users/$ME/following"

# Send a DM
curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"text":"hi"}' "$B/2/dm_conversations/with/44196397/messages"
```

Media: `POST /2/media/upload?media_type=image/jpeg` with the raw file as the body, then pass the
returned `data.media_id` in `media_ids` to `POST /2/tweets` (max 4). Video/GIF uses the same
endpoint with chunked upload handled server-side.

## Write safety

- Writes are real and public. Confirm with the user before posting, deleting, following, blocking,
  muting, or sending DMs unless they already gave an explicit instruction.
- X rate limits apply: code `344` = daily tweet limit, `226` = auth/automation rejection, `429` =
  back off. Do not retry writes aggressively.
- Some endpoints are intentional `501` stubs (XChat, Spaces buyers/creator lookups, public keys,
  community search). Check [references/endpoints.md](references/endpoints.md) before promising them.

## Troubleshooting

| Symptom | Meaning / action |
|---|---|
| `AUTH_TOKEN_MISSING` | Add `Authorization: Bearer <token>` header |
| `AUTH_TOKEN_INVALID_FORMAT` | Token must be 40 lowercase hex chars |
| `AUTH_TOKEN_EXPIRED` | Cookie expired — user must re-copy `auth_token` from x.com |
| `UPSTREAM_AUTH_REJECTED` | X rejected the session; token may be revoked |
| Slow response (2–6s) | Endpoint is CF-gated and uses Playwright; that is expected |
| `STUB_NOT_IMPLEMENTED` / 501 | Feature needs OAuth2 or an undiscovered GraphQL op |
| `RATE_LIMIT_EXCEEDED` | Wait for `retry_after`, then retry |

For full endpoint tables and request bodies, read
[references/endpoints.md](references/endpoints.md). For runnable snippets, read
[references/examples.md](references/examples.md).
