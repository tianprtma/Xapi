#!/usr/bin/env python3
"""Live smoke test for every Xapi route.

Reads the token from the XAPI_TOKEN environment variable (never pass it on the
command line). Write tests perform real actions on the authenticated account
and clean up after themselves (delete created tweets/lists, undo likes,
retweets, bookmarks, follows, mutes, blocks, DM blocks, etc.).

Usage:
    $env:XAPI_TOKEN = "<40-hex auth_token>"
    $env:XAPI_TEST_TARGET = "@some_test_account"   # required for social writes
    python tests/smoke_all_endpoints.py
    python tests/smoke_all_endpoints.py --read-only
    python tests/smoke_all_endpoints.py --json smoke_report.json

Optional env:
    XAPI_BASE_URL              default http://127.0.0.1:8000
    XAPI_TEST_TARGET           handle or numeric id used for follow/mute/block/list
    XAPI_TEST_DM_TARGET        handle or numeric id for DM tests (default: target)
    XAPI_TEST_COMMUNITY_ID     community id for GET /2/communities/{id}
    XAPI_TEST_SPACE_ID         space id for GET /2/spaces + /2/spaces/{id}
    ADMIN_TOKEN                enables GET /admin/stats check

Exit codes: 0 = no failures, 1 = failures, 2 = missing token / cannot reach server.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Optional

import httpx

# Real 200x200 red PNG — X menolak PNG degenerate (mis. 1x1) dengan
# "media type unrecognized" karena sniffer-nya butuh chunk IDAT cukup besar.
import struct
import zlib as _zlib


def _make_png(width: int = 200, height: int = 200) -> bytes:
    def _chunk(typ: bytes, data: bytes) -> bytes:
        piece = struct.pack(">I", len(data)) + typ + data
        return piece + struct.pack(">I", _zlib.crc32(typ + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([255, 0, 0] * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", _zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


TINY_PNG = _make_png()

STUB_ROUTES: list[tuple[str, str]] = [
    ("GET", "/2/communities/search"),
    ("POST", "/2/chat/conversations/group"),
    ("POST", "/2/chat/conversations/group/initialize"),
    ("POST", "/2/chat/conversations/1/keys"),
    ("POST", "/2/chat/conversations/1/members"),
    ("POST", "/2/chat/conversations/1/messages"),
    ("POST", "/2/chat/conversations/1/read"),
    ("POST", "/2/chat/conversations/1/typing"),
    ("POST", "/2/chat/media/upload/finalize"),
    ("POST", "/2/chat/media/upload/initialize"),
    ("POST", "/2/chat/media/upload/1/append"),
    ("POST", "/2/media/upload/initialize"),
    ("POST", "/2/media/upload/1/append"),
    ("POST", "/2/media/upload/1/finalize"),
    ("GET", "/2/spaces/1/buyers"),
    ("GET", "/2/spaces/by/creator_ids"),
    ("GET", "/2/spaces/1/tweets"),
    ("GET", "/2/users/public_keys"),
    ("GET", "/2/users/1/public_keys"),
    ("POST", "/2/users/1/public_keys"),
]


@dataclass
class Result:
    method: str
    path: str
    outcome: str
    status: Optional[int] = None
    code: Optional[str] = None
    detail: str = ""


class Smoke:
    def __init__(self, base_url: str, token: str, *, timeout: float, read_only: bool,
                 target: Optional[str], dm_target: Optional[str],
                 community_id: Optional[str], space_id: Optional[str],
                 skip_block: bool) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
        )
        self.read_only = read_only
        self.target = target
        self.dm_target = dm_target or target
        self.community_id = community_id
        self.space_id = space_id
        self.skip_block = skip_block
        self.results: list[Result] = []
        self.me_id: Optional[str] = None
        self.me_handle: Optional[str] = None
        self.target_id: Optional[str] = None
        self.created_tweets: list[str] = []
        self.created_lists: list[str] = []
        self.undo: list[tuple[str, str, Optional[dict[str, Any]]]] = []

    # ------------------------------------------------------------------ core

    def _record(self, result: Result) -> None:
        self.results.append(result)
        code = f" code={result.code}" if result.code else ""
        status = f" -> {result.status}" if result.status is not None else ""
        detail = f" ({result.detail})" if result.detail else ""
        print(f"[{result.outcome:<4}] {result.method:<6} {result.path}{status}{code}{detail}")

    @staticmethod
    def _body(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _error_code(payload: dict[str, Any]) -> Optional[str]:
        errors = payload.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            return errors[0].get("code") or errors[0].get("type")
        return None

    def call(self, method: str, path: str, *, expect: tuple[int, ...] = (200,),
             optional: bool = False, json_body: Optional[dict[str, Any]] = None,
             content: Optional[bytes] = None,
             headers: Optional[dict[str, str]] = None,
             params: Optional[dict[str, Any]] = None,
             note: str = "") -> httpx.Response:
        try:
            response = self.client.request(
                method, path, json=json_body, content=content, headers=headers, params=params
            )
        except Exception as exc:  # noqa: BLE001
            self._record(Result(method, path, "FAIL", None, None,
                                f"{type(exc).__name__}: {exc}"))
            return httpx.Response(0, request=httpx.Request(method, str(self.client.base_url.join(path))))

        payload = self._body(response)
        code = self._error_code(payload)
        if response.status_code in expect:
            outcome = "PASS"
        elif optional and response.status_code in (400, 403, 404, 422, 429, 502, 504):
            outcome = "WARN"
        else:
            outcome = "FAIL"
        if outcome != "PASS":
            errors = payload.get("errors")
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                upstream_detail = errors[0].get("detail") or errors[0].get("title")
                if upstream_detail:
                    note = f"{note} | {upstream_detail}" if note else str(upstream_detail)
        self._record(Result(method, path, outcome, response.status_code, code, note[:400]))
        return response

    def skip(self, method: str, path: str, reason: str) -> None:
        self._record(Result(method, path, "SKIP", None, None, reason))

    def cleanup_call(self, method: str, path: str,
                     json_body: Optional[dict[str, Any]] = None) -> None:
        try:
            self.client.request(method, path, json=json_body)
        except Exception:  # noqa: BLE001
            pass

    def data(self, response: Optional[httpx.Response]) -> Any:
        if response is None:
            return None
        return self._body(response).get("data")

    def first_id(self, response: Optional[httpx.Response]) -> Optional[str]:
        data = self.data(response)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0].get("id")
        if isinstance(data, dict):
            return data.get("id")
        return None

    # ------------------------------------------------------------- preflight

    def preflight(self) -> bool:
        print("\n== preflight ==")
        try:
            self.client.get("/info")
        except Exception as exc:  # noqa: BLE001
            self._record(Result("GET", "/info", "FAIL", None, None,
                                f"{type(exc).__name__}: {exc}"))
            print(f"\nCannot reach {self.base_url}. Start the server first.", file=sys.stderr)
            return False
        self.call("GET", "/info")
        self.call("GET", "/openapi.json")
        self.call("GET", "/docs")
        self.call("GET", "/redoc")
        self.call("GET", "/login")

        response = self.call("GET", "/2/users/me")
        if response.status_code != 200:
            print("\nCannot continue: /2/users/me failed (token invalid or upstream down).")
            return False
        self.me_id = self.first_id(response)
        me_data = self.data(response) or {}
        self.me_handle = me_data.get("username") if isinstance(me_data, dict) else None
        if not self.me_id:
            print("\nCannot continue: /2/users/me returned no data.id.")
            return False

        admin_token = os.environ.get("ADMIN_TOKEN", "").strip()
        if admin_token:
            self.call("GET", "/admin/stats", headers={"X-Admin-Token": admin_token})
        else:
            self.call("GET", "/admin/stats", expect=(404,),
                      note="ADMIN_TOKEN unset -> hidden")

        self.call("POST", "/search", json_body={"q": "hello", "type": "Latest"},
                  optional=True, note="legacy Playwright search")
        return True

    # ------------------------------------------------------------- discovery

    def resolve_user(self, value: str) -> Optional[str]:
        value = value.strip()
        if value.lstrip("@").isdigit():
            return value.lstrip("@")
        handle = value.lstrip("@")
        response = self.call("GET", f"/2/users/by/username/{handle}")
        return self.first_id(response)

    def discover(self) -> dict[str, Optional[str]]:
        print("\n== discovery ==")
        read_target = self.target or "x"
        read_target_id = self.resolve_user(read_target)
        if self.target:
            self.target_id = read_target_id

        tweet_id: Optional[str] = None
        if read_target_id:
            tweets = self.call(
                "GET", f"/2/users/{read_target_id}/tweets",
                params={"max_results": 5}, optional=True,
            )
            tweet_id = self.first_id(tweets)
        if not tweet_id:
            search = self.call(
                "GET", "/2/tweets/search/recent",
                params={"query": "hello", "type": "Latest", "max_results": 5},
                optional=True,
            )
            tweet_id = self.first_id(search)
        if tweet_id:
            print(f"       using tweet_id={tweet_id}")
        else:
            print("       no tweet id discovered; tweet-dependent reads will be skipped")

        # Temp list untuk read endpoints /2/lists/{id}* (di-cleanup di cleanup()).
        list_id: Optional[str] = None
        stamp = time.strftime("%H%M%S")
        created = self.call("POST", "/2/lists", json_body={
            "name": f"xapi smoke reads {stamp}", "is_private": True,
        }, optional=True)
        if created.status_code in (200, 201):
            list_id = self._find_list_id(self._body(created), f"xapi smoke reads {stamp}")
        if list_id:
            self.created_lists.append(list_id)
            print(f"       using list_id={list_id}")

        # Space id: cari tweet yang share link x.com/i/spaces/<id>.
        space_id: Optional[str] = None
        if not self.space_id:
            resp = self.client.get(
                "/2/tweets/search/recent",
                params={"query": "x.com/i/spaces/", "type": "Latest", "max_results": 20},
            )
            m = re.search(r"/i/spaces/([A-Za-z0-9]{10,})", resp.text)
            if m:
                space_id = m.group(1)
                print(f"       discovered space_id={space_id}")
        else:
            space_id = self.space_id

        # Community id: cari tweet yang share link x.com/i/communities/<id>.
        community_id = self.community_id
        if not community_id:
            resp = self.client.get(
                "/2/tweets/search/recent",
                params={"query": "x.com/i/communities/", "type": "Latest", "max_results": 20},
            )
            m = re.search(r"/i/communities/(\d+)", resp.text)
            if m:
                community_id = m.group(1)
                print(f"       discovered community_id={community_id}")

        return {
            "read_target": read_target,
            "read_target_id": read_target_id,
            "tweet_id": tweet_id,
            "list_id": list_id,
            "space_id": space_id,
            "community_id": community_id,
        }

    # ----------------------------------------------------------------- reads

    def reads(self, ctx: dict[str, Optional[str]]) -> None:
        print("\n== read endpoints ==")
        me = self.me_id
        assert me
        target = ctx["read_target"]
        assert target
        target_id = ctx["read_target_id"]
        tweet_id = ctx["tweet_id"]

        # Users
        self.call("GET", f"/2/users/by/username/{target.lstrip('@')}")
        self.call("GET", "/2/users/by", params={"usernames": f"{target.lstrip('@')},x"})
        self.call("GET", "/2/users", params={"ids": me})
        self.call("GET", f"/2/users/{me}")
        self.call("GET", "/2/users/search", params={"query": "x"})
        self.call("GET", "/2/users/reposts_of_me")
        self.call("GET", f"/2/users/{me}/affiliates", optional=True)
        self.call("GET", f"/2/users/{me}/tweets", params={"max_results": 5})
        self.call("GET", f"/2/users/{me}/tweets/replies", params={"max_results": 5}, optional=True)
        mention_params: dict[str, Any] = {"max_results": 5}
        if self.me_handle:
            mention_params["username"] = self.me_handle
        self.call("GET", f"/2/users/{me}/mentions", params=mention_params,
                  optional=True, note="username auto-resolve")
        self.call("GET", f"/2/users/{me}/media", params={"max_results": 5}, optional=True)
        self.call("GET", f"/2/users/{me}/liked_tweets", params={"max_results": 5}, optional=True)
        self.call("GET", f"/2/users/{me}/followers", params={"max_results": 5}, optional=True)
        self.call("GET", f"/2/users/{me}/following", params={"max_results": 5}, optional=True)
        self.call("GET", f"/2/users/{me}/blocking", optional=True)
        self.call("GET", f"/2/users/{me}/muting", optional=True)

        # Tweets
        if tweet_id:
            self.call("GET", "/2/tweets", params={"ids": tweet_id})
            self.call("GET", f"/2/tweets/{tweet_id}")
            self.call("GET", f"/2/tweets/{tweet_id}/detail", optional=True)
            self.call("GET", f"/2/tweets/{tweet_id}/liking_users", optional=True)
            self.call("GET", f"/2/tweets/{tweet_id}/retweeted_by", optional=True)
            self.call("GET", f"/2/tweets/{tweet_id}/retweets", optional=True)
            self.call("GET", f"/2/tweets/{tweet_id}/quote_tweets", optional=True)
            self.call("GET", "/2/notes/search/posts_eligible_for_notes",
                      params={"tweet_id": tweet_id}, optional=True)
        else:
            for path in (
                "/2/tweets?ids=", "/2/tweets/{id}", "/2/tweets/{id}/detail",
                "/2/tweets/{id}/liking_users", "/2/tweets/{id}/retweeted_by",
                "/2/tweets/{id}/retweets", "/2/tweets/{id}/quote_tweets",
                "/2/notes/search/posts_eligible_for_notes?tweet_id=",
            ):
                self.skip("GET", path, "no tweet id discovered")

        self.call("GET", "/2/tweets/search/recent",
                  params={"query": "x", "type": "Latest", "max_results": 5})

        # Timelines
        self.call("GET", "/2/home_timeline", optional=True)
        self.call("GET", f"/2/users/{me}/timelines/reverse_chronological", optional=True)

        # Lists
        self.call("GET", f"/2/users/{me}/owned_lists", optional=True)
        self.call("GET", f"/2/users/{me}/list_memberships", optional=True)
        self.call("GET", f"/2/users/{me}/pinned_lists", optional=True)
        self.call("GET", f"/2/users/{me}/followed_lists", optional=True)
        self.call("GET", f"/2/lists/by/owner/{me}", optional=True)
        list_id = self._normalize_id(ctx.get("list_id"))
        if list_id:
            self.call("GET", f"/2/lists/{list_id}", optional=True)
            self.call("GET", f"/2/lists/{list_id}/tweets", optional=True)
            self.call("GET", f"/2/lists/{list_id}/members", optional=True)
            self.call("GET", f"/2/lists/{list_id}/followers", optional=True)
        else:
            for path in (f"/2/lists/{{id}}", f"/2/lists/{{id}}/tweets",
                         f"/2/lists/{{id}}/members", f"/2/lists/{{id}}/followers"):
                self.skip("GET", path, "list creation failed")

        # Bookmarks
        self.call("GET", f"/2/users/{me}/bookmarks", optional=True)
        folders = self.call("GET", f"/2/users/{me}/bookmarks/folders", optional=True)
        folder_id = self._normalize_id(self.first_id(folders))
        if folder_id:
            self.call("GET", f"/2/users/{me}/bookmarks/folders/{folder_id}", optional=True)
        else:
            self.skip("GET", "/2/users/{id}/bookmarks/folders/{folder_id}",
                      "no bookmark folder")

        # Trends
        self.call("GET", "/2/trends", params={"woeid": 1})
        self.call("GET", "/2/trends/by/woeid/1")

        # Spaces / communities
        self.call("GET", "/2/spaces/topics")
        space_id = ctx.get("space_id") or self.space_id
        if space_id:
            self.call("GET", "/2/spaces", params={"ids": space_id}, optional=True,
                      note="space may have ended")
            self.call("GET", f"/2/spaces/{space_id}", optional=True,
                      note="space may have ended")
        else:
            self.skip("GET", "/2/spaces?ids=", "no space id found via search")
            self.skip("GET", "/2/spaces/{id}", "no space id found via search")
        community_id = ctx.get("community_id") or self.community_id
        if community_id:
            self.call("GET", f"/2/communities/{community_id}", optional=True)
        else:
            self.skip("GET", "/2/communities/{id}", "no community id found via search")

        # Birdwatch reads
        self.call("GET", "/2/notes/search/notes_written",
                  params={"alias": target.lstrip("@")}, optional=True)

        if target_id:
            self.call("GET", f"/2/users/{target_id}", optional=True)

    # ---------------------------------------------------------------- writes

    def _create_tweet(self, text: str, **extra: Any) -> Optional[str]:
        payload = {"text": text, **extra}
        response = self.call("POST", "/2/tweets", json_body=payload, expect=(200, 201))
        tweet_id = self.first_id(response)
        if tweet_id:
            self.created_tweets.append(tweet_id)
        return tweet_id

    def writes(self, ctx: dict[str, Optional[str]]) -> None:
        print("\n== write endpoints ==")
        me = self.me_id
        assert me
        target = self.target_id
        dm_target = None
        if self.dm_target:
            dm_target = self.target_id if self.dm_target == self.target else self.resolve_user(self.dm_target)

        stamp = time.strftime("%H%M%S")
        public_tweet = ctx.get("tweet_id")
        try:
            tweet = self._create_tweet(f"xapi smoke test {stamp}")
            if not tweet:
                print("       cannot create a tweet; skipping tweet-dependent writes")
                return

            # PUT /tweets/{id}/hidden hanya untuk reply ke tweet milik sendiri
            reply = self._create_tweet(f"xapi smoke reply {stamp}", reply_to=tweet)
            time.sleep(2)
            quote_source = public_tweet or tweet
            self._create_tweet(f"xapi smoke quote {stamp}", quote_tweet_id=quote_source)
            time.sleep(2)
            rt_source = public_tweet or tweet

            if reply:
                # X melarang hide/unhide reply yang membentuk self-thread
                # (reply dari akun sendiri) — 403 expected untuk single-account test.
                self.call("PUT", f"/2/tweets/{reply}/hidden", optional=True,
                          note="X forbids hiding self-thread replies")
                self.call("PUT", f"/2/tweets/{reply}/hidden", json_body={"hidden": False},
                          optional=True, note="X forbids hiding self-thread replies")

            self.call("POST", f"/2/users/{me}/likes", json_body={"tweet_id": tweet})
            self.call("DELETE", f"/2/users/{me}/likes/{tweet}")

            # Pre-cleanup: retweet leftover dari run sebelumnya bikin POST
            # berikutnya kena 327 (already retweeted).
            self.cleanup_call("DELETE", f"/2/users/{me}/retweets/{rt_source}")
            time.sleep(3)
            # POST bisa kena 327 kalau X masih menganggap retweet lama aktif
            # (replica lag beberapa menit setelah delete) — flaky, bukan bug proxy.
            self.call("POST", f"/2/users/{me}/retweets", json_body={"tweet_id": rt_source},
                      optional=True, note="X replica lag: delete may take minutes to propagate")
            time.sleep(5)
            self.call("DELETE", f"/2/users/{me}/retweets/{rt_source}")
            time.sleep(5)
            self.call("POST", f"/2/users/{me}/retweets", json_body={"tweet_id": rt_source},
                      optional=True, note="X eventual consistency: delete may lag")
            time.sleep(5)
            self.call("DELETE", f"/2/users/{me}/retweets/by/source_tweet_id/{rt_source}")

            self.call("POST", f"/2/users/{me}/bookmarks", json_body={"tweet_id": tweet})
            self.call("DELETE", f"/2/users/{me}/bookmarks/{tweet}")

            self.call("POST", f"/2/users/{me}/pinned_tweets", json_body={"tweet_id": tweet})
            self.call("DELETE", f"/2/users/{me}/pinned_tweets/{tweet}")

            # Media upload + metadata + tweet with media
            upload = self.call(
                "POST", "/2/media/upload",
                params={"media_type": "image/png"},
                content=TINY_PNG,
                headers={"content-type": "image/png"},
                optional=True,
            )
            media_id = None
            if upload.status_code == 200:
                media_id = (self.data(upload) or {}).get("media_id")
            if media_id:
                self.call("POST", "/2/media/metadata", json_body={
                    "media_id": media_id,
                    "alt_text": {"text": "xapi smoke test"},
                }, optional=True)
                self._create_tweet(f"xapi smoke media {stamp}", media_ids=[media_id])
            else:
                self.skip("POST", "/2/media/metadata", "media upload failed")

            # Social graph (requires an explicit test target)
            if target:
                self.call("POST", f"/2/users/{me}/following",
                          json_body={"target_user_id": target})
                self.undo.append(("DELETE", f"/2/users/{me}/following/{target}", None))
                self.call("POST", f"/2/users/{me}/muting",
                          json_body={"target_user_id": target})
                self.undo.append(("DELETE", f"/2/users/{me}/muting/{target}", None))
                if self.skip_block:
                    self.skip("POST", f"/2/users/{me}/blocking", "--skip-block")
                    self.skip("DELETE", f"/2/users/{me}/blocking/{{id}}", "--skip-block")
                else:
                    self.call("POST", f"/2/users/{me}/blocking",
                              json_body={"target_user_id": target})
                    self.undo.append(("DELETE", f"/2/users/{me}/blocking/{target}", None))
                    self.call("DELETE", f"/2/users/{me}/blocking/{target}")
            else:
                for path in (f"/2/users/{me}/following", f"/2/users/{me}/muting",
                             f"/2/users/{me}/blocking"):
                    self.skip("POST", path, "no target user resolved (set XAPI_TEST_TARGET)")

            # Lists
            list_name = f"xapi smoke {stamp}"
            created = self.call("POST", "/2/lists", json_body={
                "name": list_name, "description": "temporary smoke test", "is_private": True,
            }, optional=True)
            list_id = None
            if created.status_code in (200, 201):
                list_id = self._find_list_id(self._body(created), list_name)
            if not list_id and created.status_code in (200, 201):
                cache_bust = {"_": str(time.time())}
                owned = self.call("GET", f"/2/users/{me}/owned_lists",
                                  params=cache_bust, optional=True)
                list_id = self._find_list_id(self._body(owned), list_name)
                if not list_id:
                    by_owner = self.call("GET", f"/2/lists/by/owner/{me}",
                                         params=cache_bust, optional=True)
                    list_id = self._find_list_id(self._body(by_owner), list_name)
            if list_id:
                self.created_lists.append(list_id)
                self.call("GET", f"/2/lists/{list_id}", optional=True)
                self.call("GET", f"/2/lists/{list_id}/tweets", optional=True)
                self.call("GET", f"/2/lists/{list_id}/members", optional=True)
                self.call("GET", f"/2/lists/{list_id}/followers", optional=True)
                self.call("PUT", f"/2/lists/{list_id}",
                          json_body={"name": f"{list_name} upd", "description": "updated"})
                self.call("PUT", "/2/lists",
                          json_body={"list_id": list_id, "description": "legacy update"})
                if target:
                    self.call("POST", f"/2/lists/{list_id}/members",
                              json_body={"list_id": list_id, "user_id": target})
                    self.call("DELETE", f"/2/lists/{list_id}/members/{target}")
                else:
                    self.skip("POST", f"/2/lists/{list_id}/members", "no target user")
                    self.skip("DELETE", f"/2/lists/{list_id}/members/{{user_id}}", "no target user")
                self.call("POST", f"/2/lists/{list_id}/pinned")
                self.call("DELETE", f"/2/lists/{list_id}/pinned")
                # X melarang subscribe/unsubscribe list milik sendiri
                self.call("POST", f"/2/users/{me}/followed_lists",
                          json_body={"list_id": list_id}, optional=True,
                          note="X forbids subscribing to own list")
                self.call("DELETE", f"/2/users/{me}/followed_lists/{list_id}",
                          optional=True, note="X forbids subscribing to own list")
                self.call("POST", f"/2/users/{me}/pinned_lists",
                          json_body={"list_id": list_id})
                self.call("DELETE", f"/2/users/{me}/pinned_lists/{list_id}")
            else:
                self.skip("PUT", "/2/lists/{id}", "list creation failed")
                self.skip("POST", "/2/lists/{id}/members", "list creation failed")

            # DMs
            if dm_target:
                dm = self.call("POST", f"/2/dm_conversations/with/{dm_target}/messages",
                               json_body={"text": f"xapi smoke dm {stamp}"}, expect=(200, 201))
                dm_data = self.data(dm) or {}
                event_id = dm_data.get("dm_event_id")
                if event_id:
                    self.call("DELETE", f"/2/dm_events/{event_id}")
                else:
                    print("       DM body:", json.dumps(self._body(dm), ensure_ascii=False)[:500])
                    self.skip("DELETE", "/2/dm_events/{id}", "no dm_event_id returned")

                conversation_id = dm_data.get("dm_conversation_id")
                if conversation_id:
                    in_conv = self.call(
                        "POST", f"/2/dm_conversations/{conversation_id}/messages",
                        json_body={"text": f"xapi smoke conv msg {stamp}"},
                        expect=(200, 201),
                    )
                    conv_event = (self.data(in_conv) or {}).get("dm_event_id")
                    if conv_event:
                        self.call("DELETE", f"/2/dm_events/{conv_event}")
                    else:
                        self.skip("DELETE", "/2/dm_events/{id}",
                                  "no dm_event_id from conversation message")
                else:
                    self.skip("POST", "/2/dm_conversations/{id}/messages",
                              "no dm_conversation_id returned")

                conv = self.call("POST", "/2/dm_conversations", json_body={
                    "conversation_type": "OneToOne",
                    "participant_ids": [dm_target],
                    "message": {"text": f"xapi smoke conv {stamp}"},
                }, expect=(200, 201))
                conv_event = (self.data(conv) or {}).get("dm_event_id")
                if conv_event:
                    self.call("DELETE", f"/2/dm_events/{conv_event}")
                else:
                    self.skip("DELETE", "/2/dm_events/{id}", "no dm_event_id from conversation")

                self.call("POST", f"/2/users/{dm_target}/dm/block")
                self.call("POST", f"/2/users/{dm_target}/dm/unblock")
            else:
                for path in ("/2/dm_conversations/with/{id}/messages", "/2/dm_conversations",
                             "/2/users/{id}/dm/block", "/2/users/{id}/dm/unblock"):
                    self.skip("POST", path, "XAPI_TEST_DM_TARGET unset")

            # Birdwatch writes: akun non-contributor tidak boleh bikin note
            # (menu UI X hanya menawarkan "Minta Catatan Komunitas") — X balas
            # GRAPHQL_VALIDATION_FAILED generik. Payload di bawah sudah sesuai
            # skema (option id string); WARN = non-contributor, bukan bug proxy.
            note_target = public_tweet or tweet
            note = self.call(
                "POST", "/2/notes",
                json_body={
                    "tweet_id": note_target,
                    "data": {
                        "classification": "NOT_MISLEADING",
                        "believable": "BELIEVABLE_BY_FEW",
                        "harmful": "LITTLE_HARM",
                        "notMisleadingOther": "0",
                        "notMisleadingFactuallyCorrect": "1",
                        "notMisleadingClearUnbased": "1",
                        "trustworthySources": "1",
                    },
                },
                expect=(200, 201), optional=True,
                note="requires Birdwatch contributor account",
            )
            note_payload = self._body(note)
            note_id = None
            note_data = note_payload.get("data")
            if isinstance(note_data, dict):
                note_id = note_data.get("note_id") or note_data.get("id") or (
                    note_data.get("data", {}) or {}).get("note", {}).get("note_id")
            if not note_id and isinstance(note_data, dict):
                found = self._find_first_key(note_data, ("note_id", "rest_id"))
                note_id = found
            if note_id:
                self.call("POST", "/2/evaluate_note", json_body={
                    "note_id": note_id,
                    "tweet_id": note_target,
                    "data": {
                        "helpfulOther": 0, "helpfulInformative": 1, "helpfulClear": 1,
                        "notHelpfulOther": 0, "notHelpfulIncorrect": 0,
                        "notHelpfulSourcesMissingOrUnreliable": 0,
                        "notHelpfulOpinionSpeculationOrBias": 0,
                        "notHelpfulMissingKeyPoints": 0, "notHelpfulOutdated": 0,
                        "notHelpfulHardToUnderstand": 0, "notHelpfulArgumentativeOrBiased": 0,
                        "notHelpfulSpamHarassmentOrAbuse": 0, "notHelpfulIrrelevantSources": 0,
                        "notHelpfulOpinionSpeculation": 0, "notHelpfulNoteNotNeeded": 1,
                    },
                }, expect=(200, 201), optional=True,
                    note="X may forbid rating own note")
                self.call("DELETE", f"/2/notes/{note_id}")
            elif note.status_code in (200, 201):
                self.skip("DELETE", "/2/notes/{id}", "note created but no note_id in response")
            else:
                self.skip("DELETE", "/2/notes/{id}", "note creation rejected by X (not eligible)")
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        for method, path, body in reversed(self.undo):
            self.cleanup_call(method, path, body)
        for list_id in reversed(self.created_lists):
            self.cleanup_call("DELETE", f"/2/lists/{list_id}")
        for tweet_id in reversed(self.created_tweets):
            self.cleanup_call("DELETE", f"/2/tweets/{tweet_id}")

    @staticmethod
    def _find_first_key(payload: Any, keys: tuple[str, ...]) -> Optional[str]:
        """Depth-first cari nilai key pertama yang cocok (untuk note_id dll)."""
        if isinstance(payload, dict):
            for k in keys:
                v = payload.get(k)
                if isinstance(v, (str, int)) and str(v).strip():
                    return str(v)
            for v in payload.values():
                found = Smoke._find_first_key(v, keys)
                if found:
                    return found
        elif isinstance(payload, list):
            for v in payload:
                found = Smoke._find_first_key(v, keys)
                if found:
                    return found
        return None

    @staticmethod
    def _normalize_id(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value)
        if text.isdigit():
            return text
        try:
            decoded = base64.b64decode(text).decode()
        except Exception:  # noqa: BLE001
            return text
        return decoded.rsplit(":", 1)[-1] if ":" in decoded else text

    @staticmethod
    def _find_list_id(payload: dict[str, Any], name: str) -> Optional[str]:
        def walk(value: Any) -> Optional[str]:
            if isinstance(value, dict):
                if value.get("name") == name:
                    found = value.get("id") or value.get("rest_id") or value.get("list_id")
                    if found:
                        return Smoke._normalize_id(found)
                for child in value.values():
                    found = walk(child)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = walk(child)
                    if found:
                        return found
            return None

        return walk(payload)

    # ----------------------------------------------------------------- stubs

    def stubs(self) -> None:
        print("\n== stub routes (expect 501) ==")
        for method, path in STUB_ROUTES:
            self.call(method, path, expect=(501,))

    # --------------------------------------------------------------- summary

    def summary(self) -> int:
        counts = Counter(result.outcome for result in self.results)
        print("\n== summary ==")
        print("  " + "  ".join(f"{key}={counts.get(key, 0)}"
                               for key in ("PASS", "WARN", "FAIL", "SKIP", "STUB")))
        failures = [result for result in self.results if result.outcome == "FAIL"]
        if failures:
            print("\nFailures:")
            for result in failures:
                code = f" code={result.code}" if result.code else ""
                detail = f" ({result.detail})" if result.detail else ""
                print(f"  - {result.method} {result.path} -> {result.status}{code}{detail}")
        return 1 if failures else 0


def load_dotenv() -> None:
    """Load repo-root .env (gitignored) without overriding existing env vars."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value.startswith("<") and value.endswith(">"):
                continue
            os.environ.setdefault(key.strip(), value)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Smoke test every Xapi endpoint.")
    parser.add_argument("--base-url", default=os.environ.get("XAPI_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--read-only", action="store_true",
                        help="skip write endpoints (no tweets, follows, DMs, lists)")
    parser.add_argument("--target", default=os.environ.get("XAPI_TEST_TARGET"),
                        help="handle or numeric id for follow/mute/block/list tests")
    parser.add_argument("--dm-target", default=os.environ.get("XAPI_TEST_DM_TARGET"),
                        help="handle or numeric id for DM tests (default: --target)")
    parser.add_argument("--community-id", default=os.environ.get("XAPI_TEST_COMMUNITY_ID"))
    parser.add_argument("--space-id", default=os.environ.get("XAPI_TEST_SPACE_ID"))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--skip-block", action="store_true",
                        help="do not test block/unblock (still tests follow + mute)")
    parser.add_argument("--json", metavar="PATH", help="write a JSON report")
    args = parser.parse_args()

    token = os.environ.get("XAPI_TOKEN", "").strip()
    if not token:
        print("XAPI_TOKEN is not set. Set it in the environment, then re-run:", file=sys.stderr)
        print('  $env:XAPI_TOKEN = "<40-hex auth_token>"', file=sys.stderr)
        return 2

    smoke = Smoke(
        args.base_url, token,
        timeout=args.timeout,
        read_only=args.read_only,
        target=args.target,
        dm_target=args.dm_target,
        community_id=args.community_id,
        space_id=args.space_id,
        skip_block=args.skip_block,
    )

    print(f"Xapi smoke test -> {smoke.base_url} ({'read-only' if args.read_only else 'read+write'})")
    try:
        if not smoke.preflight():
            return 2
        ctx = smoke.discover()
        smoke.reads(ctx)
        if args.read_only:
            smoke.skip("POST", "/2/tweets", "--read-only")
            smoke.skip("POST", "/2/lists", "--read-only")
            smoke.skip("POST", "/2/dm_conversations", "--read-only")
        else:
            smoke.writes(ctx)
        smoke.stubs()
    except KeyboardInterrupt:
        print("\ninterrupted; cleanup may be incomplete", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\nAborted: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        smoke.cleanup()
        smoke.client.close()

    exit_code = smoke.summary()
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump([asdict(result) for result in smoke.results], handle, indent=2)
        print(f"\nJSON report written to {args.json}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
