#!/usr/bin/env bash
# E2E test all Xapi endpoints. Returns HTTP status + brief data preview per endpoint.
set -uo pipefail
TOKEN="${XAPI_TOKEN:-ce0a0018db6dc533709806a513b07900c350a7b7}"
ME="${XAPI_ME:-1391552089424158720}"
HANDLE="${XAPI_HANDLE:-UhJilbab}"
TARGET="${XAPI_TARGET:-44196397}"          # elonmusk
TWEET_PUBLIC="${XAPI_TWEET:-2055294612751991090}"  # has likes/retweets
H="http://127.0.0.1:8000"
AUTH=(-H "Authorization: Bearer $TOKEN")
JSONH=(-H "Content-Type: application/json")
PASS=0; FAIL=0; SKIP=0
declare -a FAILS

run() {
  local name="$1" method="$2" url="$3" expect_field="$4" body="${5:-}"
  local out status data_ok
  if [ -n "$body" ]; then
    out=$(/usr/bin/curl -s -w '\n%{http_code}' -X "$method" "${AUTH[@]}" "${JSONH[@]}" -d "$body" "$H$url")
  else
    out=$(/usr/bin/curl -s -w '\n%{http_code}' -X "$method" "${AUTH[@]}" "$H$url")
  fi
  status=$(echo "$out" | tail -1)
  data=$(echo "$out" | sed '$d')
  printf "%-58s %s " "$name" "$status"
  if [ "$status" = "200" ]; then
    if [ -n "$expect_field" ]; then
      if echo "$data" | python3 -c "import sys,json; d=json.load(sys.stdin); k='$expect_field'.split('.'); v=d
for x in k: v = v.get(x) if isinstance(v,dict) else (v[int(x)] if isinstance(v,list) else None)
sys.exit(0 if v is not None else 1)" 2>/dev/null; then
        echo "OK"; PASS=$((PASS+1))
      else
        echo "OK_BUT_FIELD_MISSING ($expect_field)"
        echo "  $(echo "$data" | head -c 200)"
        FAIL=$((FAIL+1)); FAILS+=("$name field=$expect_field")
      fi
    else
      echo "OK"; PASS=$((PASS+1))
    fi
  else
    echo "FAIL"
    echo "  $(echo "$data" | head -c 250)"
    FAIL=$((FAIL+1)); FAILS+=("$name status=$status")
  fi
}

echo "=== infra ==="
run "GET /"                       GET  "/" "service"

echo
echo "=== reads ==="
run "GET /2/users/me"             GET  "/2/users/me" "data.id"
run "GET /2/users/by/username"    GET  "/2/users/by/username/elonmusk" "data.id"
run "GET /2/users/{id}"           GET  "/2/users/$TARGET" "data.id"
run "GET /tweets/{id}"            GET  "/2/tweets/$TWEET_PUBLIC" "data.id"
run "GET /tweets/{id}/detail"     GET  "/2/tweets/$TWEET_PUBLIC/detail" "data"
run "GET /users/{id}/tweets"      GET  "/2/users/$TARGET/tweets?max_results=3" "data"
run "GET /users/{id}/replies"     GET  "/2/users/$TARGET/tweets/replies?max_results=3" "data"
run "GET /users/{id}/followers"   GET  "/2/users/$TARGET/followers?max_results=3" "data"
run "GET /users/{id}/following"   GET  "/2/users/$ME/following?max_results=3" "data"
run "GET /users/{id}/liked"       GET  "/2/users/$ME/liked_tweets?max_results=3" "data"
run "GET /users/{id}/media"       GET  "/2/users/$TARGET/media?max_results=3" "data"
run "GET /home_timeline"          GET  "/2/home_timeline?max_results=3" "data"
run "GET /reverse_chronological"  GET  "/2/users/$ME/timelines/reverse_chronological?max_results=3" "data"
run "GET /search/recent"          GET  "/2/tweets/search/recent?query=bitcoin&max_results=3" "data"

echo
echo "=== reads (new) ==="
run "GET /users/{id}/bookmarks"   GET  "/2/users/$ME/bookmarks?max_results=3" "data"
run "GET /tweets/{id}/liking"     GET  "/2/tweets/$TWEET_PUBLIC/liking_users?max_results=3" "data"
run "GET /tweets/{id}/retweeted"  GET  "/2/tweets/$TWEET_PUBLIC/retweeted_by?max_results=3" "data"
run "GET /tweets/{id}/quotes"     GET  "/2/tweets/$TWEET_PUBLIC/quote_tweets?max_results=3" "data"
run "GET /users/{id}/mentions"    GET  "/2/users/$ME/mentions?username=$HANDLE&max_results=3" "data"
run "GET /lists/by/owner"         GET  "/2/lists/by/owner/$ME" "data"
run "GET /trends"                 GET  "/2/trends?woeid=23424846" "data"

echo
echo "=== writes (idempotent like/unlike on public tweet) ==="
run "POST /likes"                 POST "/2/users/$ME/likes" "data" '{"tweet_id":"'$TWEET_PUBLIC'"}'
run "DELETE /likes/{id}"          DELETE "/2/users/$ME/likes/$TWEET_PUBLIC" "data"
run "POST /retweets"              POST "/2/users/$ME/retweets" "data" '{"tweet_id":"'$TWEET_PUBLIC'"}'
run "DELETE /retweets/{id}"       DELETE "/2/users/$ME/retweets/$TWEET_PUBLIC" "data"
run "POST /bookmarks"             POST "/2/users/$ME/bookmarks" "data" '{"tweet_id":"'$TWEET_PUBLIC'"}'
run "DELETE /bookmarks/{id}"      DELETE "/2/users/$ME/bookmarks/$TWEET_PUBLIC" "data"

echo
echo "=== writes (lists CRUD) ==="
LRESP=$(/usr/bin/curl -s -X POST "${AUTH[@]}" "${JSONH[@]}" -d '{"name":"E2E test","is_private":true}' "$H/2/lists")
LIST_ID=$(echo "$LRESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['data']['data']['list']['id_str'])" 2>/dev/null || echo "")
if [ -n "$LIST_ID" ]; then
  echo "POST /2/lists                                              200 OK (id=$LIST_ID)"; PASS=$((PASS+1))
  run "GET /lists/{id}"             GET  "/2/lists/$LIST_ID" "data"
  run "GET /lists/{id}/tweets"      GET  "/2/lists/$LIST_ID/tweets?max_results=3" "data"
  run "GET /lists/{id}/members"     GET  "/2/lists/$LIST_ID/members?max_results=3" "data"
  run "PUT /lists"                  PUT  "/2/lists" "data" "{\"list_id\":\"$LIST_ID\",\"description\":\"updated\"}"
  run "POST /lists/{id}/members"    POST "/2/lists/$LIST_ID/members" "data" "{\"list_id\":\"$LIST_ID\",\"user_id\":\"$TARGET\"}"
  run "DELETE /lists/{id}/members"  DELETE "/2/lists/$LIST_ID/members/$TARGET" "data"
  run "POST /lists/{id}/pinned"     POST "/2/lists/$LIST_ID/pinned" "data"
  run "DELETE /lists/{id}/pinned"   DELETE "/2/lists/$LIST_ID/pinned" "data"
  run "DELETE /lists/{id}"          DELETE "/2/lists/$LIST_ID" "data"
else
  echo "POST /2/lists                                              FAIL — skipping list CRUD"; FAIL=$((FAIL+1)); FAILS+=("POST /2/lists")
  echo "$LRESP" | head -c 300
fi

echo
echo "=== writes (pin tweet, follow/mute/block — non-destructive on $TARGET) ==="
run "POST /pinned_tweets"         POST "/2/users/$ME/pinned_tweets" "data" "{\"tweet_id\":\"$TWEET_PUBLIC\"}"
run "DELETE /pinned_tweets/{id}"  DELETE "/2/users/$ME/pinned_tweets/$TWEET_PUBLIC" "data"
# follow/unfollow/mute/block are reversible on a known account — keep state restored
run "POST /following"             POST "/2/users/$ME/following" "data" "{\"target_user_id\":\"$TARGET\"}"
run "DELETE /following"           DELETE "/2/users/$ME/following/$TARGET" "data"
run "POST /muting"                POST "/2/users/$ME/muting" "data" "{\"target_user_id\":\"$TARGET\"}"
run "DELETE /muting"              DELETE "/2/users/$ME/muting/$TARGET" "data"
run "POST /blocking"              POST "/2/users/$ME/blocking" "data" "{\"target_user_id\":\"$TARGET\"}"
run "DELETE /blocking"            DELETE "/2/users/$ME/blocking/$TARGET" "data"

echo
echo "=== legacy ==="
run "GET /login"                  GET  "/login?auth_token=$TOKEN" "user"
run "POST /search"                POST "/search" "data" "{\"auth_token\":\"$TOKEN\",\"q\":\"bitcoin\",\"type\":\"Latest\",\"engine\":\"playwright\"}"

echo
echo "=== batch graphql ops baru ==="
run "GET /list_memberships"       GET  "/2/users/$ME/list_memberships?max_results=3" "data"
run "GET /lists/{id}/followers"   GET  "/2/lists/1582137247017209856/followers?max_results=3" "data"
run "GET /bookmarks/folders"      GET  "/2/users/$ME/bookmarks/folders?max_results=3" "data"
run "GET /communities/{id}"       GET  "/2/communities/1493446837214187523" "data"
run "GET /notes/contributor"      GET  "/2/notes/search/notes_written?alias=$HANDLE&max_results=3" "data"
run "GET /notes/eligible"         GET  "/2/notes/search/posts_eligible_for_notes?tweet_id=$TWEET_PUBLIC" "data"

echo
echo "==================================================="
echo "PASS=$PASS  FAIL=$FAIL"
if [ $FAIL -gt 0 ]; then
  echo "Failures:"
  for f in "${FAILS[@]}"; do echo "  - $f"; done
  exit 1
fi
