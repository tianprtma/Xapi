# Xapi examples

Set these first (never hard-code the token in files you commit):

```bash
export XAPI_BASE_URL="http://127.0.0.1:8000"
export XAPI_TOKEN="<40-hex auth_token cookie>"
```

## cURL

```bash
B="$XAPI_BASE_URL"; H="Authorization: Bearer $XAPI_TOKEN"

curl -s "$B/info"
curl -s -H "$H" "$B/login"
curl -s -H "$H" "$B/2/users/me"
curl -s -H "$H" "$B/2/users/by/username/elonmusk"
curl -s -H "$H" "$B/2/users/by?usernames=elonmusk,jack"
curl -s -H "$H" "$B/2/users/44196397/tweets?max_results=20"
curl -s -H "$H" "$B/2/tweets/search/recent?query=bitcoin&type=Latest&max_results=20"
curl -s -H "$H" "$B/2/trends/by/woeid/23424775"
```

Write operations:

```bash
ME="$(curl -s -H "$H" "$B/2/users/me" | python -c "import json,sys;print(json.load(sys.stdin)['data']['id'])")"

curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"text":"hello from Xapi"}' "$B/2/tweets"

curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"text":"@user reply","reply_to":"1234567890"}' "$B/2/tweets"

curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"tweet_id":"1234567890"}' "$B/2/users/$ME/likes"

curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"target_user_id":"44196397"}' "$B/2/users/$ME/following"

curl -s -X POST -H "$H" -H "Content-Type: application/json" \
  -d '{"text":"hi"}' "$B/2/dm_conversations/with/44196397/messages"
```

## Python (httpx)

```python
import os
import httpx

BASE = os.environ.get("XAPI_BASE_URL", "http://127.0.0.1:8000")
TOKEN = os.environ["XAPI_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

with httpx.Client(base_url=BASE, headers=HEADERS, timeout=60) as c:
    me = c.get("/2/users/me").raise_for_status().json()["data"]
    print(me["id"], me["username"])

    r = c.get("/2/users/me")
    if r.status_code >= 400:
        print(r.json()["errors"][0]["code"])
        raise SystemExit(1)

    tweet = c.post("/2/tweets", json={"text": "hello from python"}).json()
    print(tweet["data"]["id"])
```

Paginate a timeline until `meta.next_token` disappears:

```python
token = None
while True:
    params = {"max_results": 100}
    if token:
        params["pagination_token"] = token
    r = httpx.get(f"{BASE}/2/users/{user_id}/tweets", headers=HEADERS, params=params, timeout=60)
    payload = r.raise_for_status().json()
    for t in payload.get("data", []):
        print(t["id"], t["text"][:80])
    token = payload.get("meta", {}).get("next_token")
    if not token:
        break
```

Search uses `next_token` as the cursor parameter instead of `pagination_token`:

```python
r = httpx.get(
    f"{BASE}/2/tweets/search/recent",
    headers=HEADERS,
    params={"query": "bitcoin", "type": "Latest", "max_results": 20},
    timeout=120,
)
```

## Media upload + tweet

```python
import httpx, os

BASE = os.environ["XAPI_BASE_URL"]
H = {"Authorization": f"Bearer {os.environ['XAPI_TOKEN']}"}

with open("foto.jpg", "rb") as f:
    up = httpx.post(
        f"{BASE}/2/media/upload",
        params={"media_type": "image/jpeg"},
        content=f.read(),
        headers=H,
        timeout=180,
    )
up.raise_for_status()
media_id = up.json()["data"]["media_id"]

post = httpx.post(
    f"{BASE}/2/tweets",
    headers=H,
    json={"text": "caption", "media_ids": [media_id]},
    timeout=60,
)
print(post.json())
```

Video/GIF: same endpoint with `media_type=video/mp4` or `image/gif`; the server performs chunked
upload and STATUS polling. Allow up to a few minutes.

## JavaScript (fetch)

```javascript
const BASE = process.env.XAPI_BASE_URL ?? "http://127.0.0.1:8000";
const HEADERS = {
  Authorization: `Bearer ${process.env.XAPI_TOKEN}`,
  "Content-Type": "application/json",
};

const res = await fetch(`${BASE}/2/users/me`, { headers: HEADERS });
if (!res.ok) {
  const { errors } = await res.json();
  throw new Error(errors[0].code);
}
const me = (await res.json()).data;

await fetch(`${BASE}/2/tweets`, {
  method: "POST",
  headers: HEADERS,
  body: JSON.stringify({ text: "hello from JS" }),
});
```

## Reading errors

```json
{
  "errors": [
    {
      "code": "AUTH_TOKEN_MISSING",
      "title": "Authentication Required",
      "detail": "missing auth_token (provide 'Authorization: Bearer <auth_token>' header)",
      "type": "unauthorized",
      "status": 401
    }
  ]
}
```

Handle these codes explicitly: `AUTH_TOKEN_MISSING`, `AUTH_TOKEN_INVALID_FORMAT`,
`AUTH_TOKEN_EXPIRED`, `UPSTREAM_AUTH_REJECTED`, `RATE_LIMIT_EXCEEDED`, `STUB_NOT_IMPLEMENTED`,
`INFRA_RAW_DISABLED`. See `docs/ERROR_CODES.md` for the full list.
