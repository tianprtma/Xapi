"""
Normalizer GraphQL X.com → format X API v2 official.

Spec: https://docs.x.com/x-api/introduction
- Single resource: {"data": {...}}
- Collection: {"data": [...], "meta": {"result_count":N, "next_token":"..."}}
- Errors: {"errors": [{"title","detail","type"}]}
- Relasi tambahan: "includes" (users, tweets, media)
"""

from __future__ import annotations

from typing import Any, Optional


# ──────────────── User normalizer ────────────────


def _user_result_to_obj(user_result: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Convert GraphQL `user_results.result` → X API v2 user object."""
    if not user_result or user_result.get("__typename") in ("UserUnavailable",):
        return None

    legacy = user_result.get("legacy", {}) or {}
    core = user_result.get("core", {}) or {}
    # X memindah lokasi avatar beberapa kali: avatar.image_url_https (lama),
    # avatar.image_url (baru), legacy.profile_image_url_https (fallback).
    _av = user_result.get("avatar") or {}
    avatar = (_av.get("image_url_https") or _av.get("image_url")
              or legacy.get("profile_image_url_https"))
    location = (user_result.get("location") or {}).get("location") or legacy.get("location")
    rel_persp = user_result.get("relationship_perspectives") or {}
    following = rel_persp.get("following") if rel_persp.get("following") is not None else legacy.get("following")
    followed_by = rel_persp.get("followed_by") if rel_persp.get("followed_by") is not None else legacy.get("followed_by")
    blocking = rel_persp.get("blocking") if rel_persp.get("blocking") is not None else legacy.get("blocking")
    muting = rel_persp.get("muting") if rel_persp.get("muting") is not None else legacy.get("muting")
    default_avatar = legacy.get("default_profile_image")
    if default_avatar is None and isinstance(avatar, str):
        default_avatar = "default_profile" in avatar
    priv_prot = (user_result.get("privacy") or {}).get("protected")

    return {
        "id": user_result.get("rest_id"),
        "name": core.get("name") or legacy.get("name"),
        "username": core.get("screen_name") or legacy.get("screen_name"),
        "created_at": core.get("created_at") or legacy.get("created_at") or _dm_ts_to_iso(core.get("created_at_ms")),
        "description": legacy.get("description"),
        "location": location,
        "url": legacy.get("url"),
        "verified": (
            user_result.get("is_blue_verified")
            or (user_result.get("verification") or {}).get("is_blue_verified")
            or legacy.get("verified")
            or False
        ),
        "protected": priv_prot if priv_prot is not None else legacy.get("protected", False),
        "profile_image_url": avatar,
        "default_profile_image": bool(default_avatar) if default_avatar is not None else False,
        "relationship": {
            "following": following,
            "followed_by": followed_by,
            "blocking": blocking,
            "muting": muting,
        },
        "public_metrics": {
            "followers_count": legacy.get("followers_count") if legacy.get("followers_count") is not None else (user_result.get("relationship_counts") or {}).get("followers"),
            "following_count": legacy.get("friends_count"),
            "tweet_count": legacy.get("statuses_count"),
            "listed_count": legacy.get("listed_count"),
            "like_count": legacy.get("favourites_count"),
            "media_count": legacy.get("media_count"),
        },
    }


def format_user(gql: dict[str, Any]) -> dict[str, Any]:
    """Format response UserByScreenName / UserByRestId."""
    user_result = (
        (gql or {}).get("data", {}).get("user", {}).get("result", {})
    )
    obj = _user_result_to_obj(user_result)
    if not obj:
        return {"errors": [{"title": "Not Found", "detail": "User not found", "type": "not_found"}]}
    return {"data": obj}


# ──────────────── Tweet normalizer ────────────────


def _tweet_result_to_obj(tweet_result: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Convert tweet_results.result → X API v2 tweet object."""
    if not tweet_result:
        return None
    # TweetWithVisibilityResults wrapper
    if tweet_result.get("__typename") == "TweetWithVisibilityResults":
        tweet_result = tweet_result.get("tweet", {}) or {}
    if tweet_result.get("__typename") == "TweetTombstone":
        return None

    legacy = tweet_result.get("legacy", {}) or {}
    note = tweet_result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {}) if tweet_result.get("note_tweet") else {}
    text = (note or {}).get("text") or legacy.get("full_text") or legacy.get("text")
    core = tweet_result.get("core", {}) or {}
    author = (
        core.get("user_results", {}).get("result", {}) if core else {}
    )

    entities = legacy.get("entities", {}) or {}

    return {
        "id": tweet_result.get("rest_id") or legacy.get("id_str"),
        "text": text,
        "author_id": author.get("rest_id") or legacy.get("user_id_str"),
        "created_at": legacy.get("created_at"),
        "lang": legacy.get("lang"),
        "conversation_id": legacy.get("conversation_id_str"),
        "in_reply_to_user_id": legacy.get("in_reply_to_user_id_str"),
        "referenced_tweets": _build_referenced(legacy),
        "public_metrics": {
            "retweet_count": legacy.get("retweet_count"),
            "reply_count": legacy.get("reply_count"),
            "like_count": legacy.get("favorite_count"),
            "quote_count": legacy.get("quote_count"),
            "bookmark_count": legacy.get("bookmark_count"),
            "impression_count": tweet_result.get("views", {}).get("count")
            if tweet_result.get("views")
            else None,
        },
        "entities": {
            "hashtags": [{"tag": h.get("text")} for h in entities.get("hashtags", [])],
            "mentions": [
                {"username": m.get("screen_name"), "id": m.get("id_str")}
                for m in entities.get("user_mentions", [])
            ],
            "urls": [
                {
                    "url": u.get("url"),
                    "expanded_url": u.get("expanded_url"),
                    "display_url": u.get("display_url"),
                }
                for u in entities.get("urls", [])
            ],
            "cashtags": [{"tag": c.get("text")} for c in entities.get("symbols", [])],
        },
        "attachments": _build_attachments(legacy),
        "possibly_sensitive": legacy.get("possibly_sensitive", False),
    }


def _build_referenced(legacy: dict[str, Any]) -> list[dict[str, str]]:
    refs = []
    if legacy.get("retweeted_status_id_str"):
        refs.append({"type": "retweeted", "id": legacy["retweeted_status_id_str"]})
    if legacy.get("quoted_status_id_str"):
        refs.append({"type": "quoted", "id": legacy["quoted_status_id_str"]})
    if legacy.get("in_reply_to_status_id_str"):
        refs.append({"type": "replied_to", "id": legacy["in_reply_to_status_id_str"]})
    return refs


def _build_attachments(legacy: dict[str, Any]) -> dict[str, Any]:
    media = (legacy.get("extended_entities", {}) or {}).get("media", []) or []
    if not media:
        return {}
    return {"media_keys": [m.get("media_key") for m in media if m.get("media_key")]}


def _media_obj(m: dict[str, Any]) -> dict[str, Any]:
    kind = m.get("type")
    url = m.get("media_url_https")
    variants: Optional[list[dict[str, Any]]] = None
    if kind in ("video", "animated_gif"):
        # Video: sertakan variants + `url` = mp4 bitrate tertinggi, supaya
        # consumer bisa download video aslinya (bukan cuma thumbnail).
        variants = [
            {"bitrate": v.get("bitrate"), "content_type": v.get("content_type"),
             "url": v.get("url")}
            for v in (m.get("video_info") or {}).get("variants") or []
            if v.get("url")
        ]
        mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
        if mp4s:
            url = max(mp4s, key=lambda v: v.get("bitrate") or 0)["url"]
    return {
        "media_key": m.get("media_key"),
        "type": kind,
        "url": url,
        "preview_image_url": m.get("media_url_https"),
        "width": (m.get("original_info") or {}).get("width"),
        "height": (m.get("original_info") or {}).get("height"),
        "alt_text": m.get("ext_alt_text"),
        **({"variants": variants} if variants else {}),
    }


def _dm_attachment_obj(m: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort flatten of a DM attachment.media object so consumers can
    download the binary directly. Differs from `_media_obj` because DM
    media uses `id_str` not `media_key`, and video variants are nested
    under `video_info.variants`.

    Returns: {kind, mime, url, width?, height?, duration_ms?, byte_size?}
    where `kind` ∈ {photo, video, animated_gif} per X DM payload.
    """
    kind = m.get("type") or "photo"
    mime: Optional[str] = None
    url: Optional[str] = m.get("media_url_https")
    width = (m.get("original_info") or {}).get("width")
    height = (m.get("original_info") or {}).get("height")
    duration_ms = (m.get("video_info") or {}).get("duration_millis")
    byte_size: Optional[int] = None

    if kind in ("video", "animated_gif"):
        # Pick highest-bitrate mp4 variant; X also returns m3u8 (HLS) which
        # we skip — re-uploading HLS to X needs a manifest fetch.
        variants = (m.get("video_info") or {}).get("variants") or []
        mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
        mp4s.sort(key=lambda v: v.get("bitrate") or 0, reverse=True)
        if mp4s:
            url = mp4s[0].get("url")
            mime = "video/mp4"
    thumbnail_url = m.get("media_url_https") if kind in ("video", "animated_gif") else None
    thumbnail_proxy_path: Optional[str] = None
    if thumbnail_url and "/ton/data/dm/" in thumbnail_url:
        t_suffix = thumbnail_url.split("/ton/data/dm/", 1)[1].split("?", 1)[0]
        thumbnail_proxy_path = f"/2/dm_conversations/media/{t_suffix}"
    if kind == "photo" and url:
        # X serves DM photos at media_url_https; format is in `format` field
        # (jpg|png|gif|webp). MIME is best-guessed from extension.
        ext = (url.rsplit(".", 1)[-1] or "").lower().split("?", 1)[0]
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp"}.get(ext) or "image/jpeg"
    if isinstance(m.get("size"), int):
        byte_size = m.get("size")

    proxy_path: Optional[str] = None
    if url and "/ton/data/dm/" in url:
        suffix = url.split("/ton/data/dm/", 1)[1].split("?", 1)[0]
        proxy_path = f"/2/dm_conversations/media/{suffix}"

    return {
        "kind": kind,
        "mime": mime,
        "url": url,
        "proxy_path": proxy_path,
        "thumbnail_url": thumbnail_url,
        "thumbnail_proxy_path": thumbnail_proxy_path,
        "width": width,
        "height": height,
        "duration_ms": duration_ms,
        "byte_size": byte_size,
        "media_id": str(m.get("id_str") or m.get("id") or ""),
    }


def format_tweet(gql: dict[str, Any]) -> dict[str, Any]:
    """Format TweetResultByRestId / CreateTweet."""
    data = (gql or {}).get("data", {})
    # Try TweetResultByRestId path first
    tw = data.get("tweetResult", {}).get("result", {})
    if not tw:
        # Try CreateTweet path (tweet_results.result format)
        tw = data.get("create_tweet", {}).get("tweet_results", {}).get("result", {})
    if not tw:
        # Try CreateTweet path (tweet format — actual CreateTweet GQL response)
        tw = data.get("create_tweet", {}).get("tweet", {})
    obj = _tweet_result_to_obj(tw)
    if not obj:
        return {"errors": [{"title": "Not Found", "detail": "Tweet not found", "type": "not_found"}]}

    includes = _collect_includes_from_tweet(tw)
    out: dict[str, Any] = {"data": obj}
    if includes:
        out["includes"] = includes
    return out


def _collect_includes_from_tweet(tweet_result: dict[str, Any]) -> dict[str, list]:
    if tweet_result.get("__typename") == "TweetWithVisibilityResults":
        tweet_result = tweet_result.get("tweet", {}) or {}

    includes: dict[str, list] = {"users": [], "media": [], "tweets": []}
    legacy = tweet_result.get("legacy", {}) or {}
    core = tweet_result.get("core", {}) or {}
    author = core.get("user_results", {}).get("result", {}) if core else {}
    a = _user_result_to_obj(author)
    if a:
        includes["users"].append(a)

    for m in (legacy.get("extended_entities", {}) or {}).get("media", []) or []:
        includes["media"].append(_media_obj(m))

    quoted = tweet_result.get("quoted_status_result", {}).get("result")
    if quoted:
        q = _tweet_result_to_obj(quoted)
        if q:
            includes["tweets"].append(q)
        # also bring quoted author
        qcore = quoted.get("core", {}) or {}
        qauthor = qcore.get("user_results", {}).get("result", {}) if qcore else {}
        qa = _user_result_to_obj(qauthor)
        if qa and qa.get("id") and qa["id"] not in {u["id"] for u in includes["users"] if u.get("id")}:
            includes["users"].append(qa)

    return {k: v for k, v in includes.items() if v}


# ──────────────── Timeline normalizer ────────────────


def _walk_timeline_entries(payload: dict[str, Any]) -> tuple[list[dict], Optional[str], Optional[str]]:
    """
    Walk timeline GraphQL → return (entries, next_cursor, prev_cursor).
    Mendukung struktur HomeTimeline, UserTweets, SearchTimeline, ListLatestTweetsTimeline, dll.
    """
    data = (payload or {}).get("data", {})
    # Coba berbagai bentuk
    candidates = [
        ("user", "result", "timeline", "timeline", "instructions"),
        ("user", "result", "timeline_v2", "timeline", "instructions"),
        ("user", "result", "timeline", "instructions"),
        ("home", "home_timeline_urt", "instructions"),
        ("threaded_conversation_with_injections_v2", "instructions"),
        ("search_by_raw_query", "search_timeline", "timeline", "instructions"),
        ("list", "tweets_timeline", "timeline", "instructions"),
        ("list", "members_timeline", "timeline", "instructions"),
        ("user", "result", "timeline", "timeline", "instructions"),
    ]
    instructions: list[dict] = []
    for path in candidates:
        node = data
        for k in path:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                node = None
                break
        if isinstance(node, list):
            instructions = node
            break

    entries: list[dict] = []
    for ins in instructions:
        if ins.get("type") == "TimelineAddEntries":
            entries.extend(ins.get("entries", []))
        elif ins.get("type") == "TimelinePinEntry":
            if ins.get("entry"):
                entries.append(ins["entry"])

    next_cursor: Optional[str] = None
    prev_cursor: Optional[str] = None
    for e in entries:
        content = e.get("content", {}) or {}
        if content.get("entryType") == "TimelineTimelineCursor":
            ct = content.get("cursorType")
            if ct == "Bottom":
                next_cursor = content.get("value")
            elif ct == "Top":
                prev_cursor = content.get("value")

    return entries, next_cursor, prev_cursor


def _flatten_module_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """TimelineTimelineModule (mis. profile-conversation / reply thread) → item tunggal."""
    out: list[dict[str, Any]] = []
    for e in entries:
        content = e.get("content", {}) or {}
        if content.get("entryType") == "TimelineTimelineModule" and isinstance(content.get("items"), list):
            for it in content["items"]:
                if isinstance(it, dict):
                    out.append({"content": it.get("item") or it.get("content") or it})
        else:
            out.append(e)
    return out


def _entry_to_tweet(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    content = entry.get("content", {}) or {}
    item_content = content.get("itemContent") or content.get("content") or {}
    if item_content.get("itemType") == "TimelineTweet":
        tw = item_content.get("tweet_results", {}).get("result", {})
        return _tweet_result_to_obj(tw)
    return None


def _entry_to_user(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    content = entry.get("content", {}) or {}
    item_content = content.get("itemContent") or {}
    if item_content.get("itemType") == "TimelineUser":
        ur = item_content.get("user_results", {}).get("result", {})
        return _user_result_to_obj(ur)
    return None


def _entry_raw_tweet(entry: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return tweet_result raw (untuk ekstrak includes)."""
    content = entry.get("content", {}) or {}
    item_content = content.get("itemContent") or content.get("content") or {}
    if item_content.get("itemType") == "TimelineTweet":
        return item_content.get("tweet_results", {}).get("result", {})
    return None


def format_tweet_collection(
    gql: dict[str, Any],
    *,
    item: str = "tweet",  # "tweet" | "user"
) -> dict[str, Any]:
    """Format timeline GraphQL → {data:[...], includes:{}, meta:{}}."""
    entries, next_cursor, prev_cursor = _walk_timeline_entries(gql)
    entries = _flatten_module_entries(entries)

    data: list[dict[str, Any]] = []
    users: dict[str, dict] = {}
    media: dict[str, dict] = {}
    refs: dict[str, dict] = {}

    for e in entries:
        if item == "user":
            u = _entry_to_user(e)
            if u and u["id"]:
                data.append(u)
        else:
            t = _entry_to_tweet(e)
            if not t:
                continue
            data.append(t)
            raw = _entry_raw_tweet(e)
            if raw:
                inc = _collect_includes_from_tweet(raw)
                for u in inc.get("users", []):
                    if u["id"] and u["id"] not in users:
                        users[u["id"]] = u
                for m in inc.get("media", []):
                    if m["media_key"] and m["media_key"] not in media:
                        media[m["media_key"]] = m
                for r in inc.get("tweets", []):
                    if r["id"] and r["id"] not in refs:
                        refs[r["id"]] = r

    meta: dict[str, Any] = {"result_count": len(data)}
    if next_cursor:
        meta["next_token"] = next_cursor
    if prev_cursor:
        meta["previous_token"] = prev_cursor

    out: dict[str, Any] = {"data": data, "meta": meta}
    includes: dict[str, list] = {}
    if users:
        includes["users"] = list(users.values())
    if media:
        includes["media"] = list(media.values())
    if refs:
        includes["tweets"] = list(refs.values())
    if includes:
        out["includes"] = includes
    return out


# ──────────────── Error wrapper ────────────────


def format_error(title: str, detail: str = "", type_: str = "error", status: int = 500) -> dict[str, Any]:
    return {
        "errors": [
            {
                "title": title,
                "detail": detail or title,
                "type": type_,
                "status": status,
            }
        ]
    }


# ──────────────── Community / Bookmark folder / Birdwatch normalizers ────────────────


def format_community(gql: dict[str, Any]) -> dict[str, Any]:
    """CommunityByRestId → simplified v2-ish shape."""
    data = (gql or {}).get("data", {}) or {}
    result = ((data.get("communityResults") or {}).get("result") or
              (data.get("community_results") or {}).get("result") or {})
    if not result or result.get("__typename") not in ("Community", None):
        if result.get("__typename") and result.get("__typename") != "Community":
            return {"errors": [{"title": "Not Found", "detail": result.get("__typename"), "type": "not_found"}]}
        return {"errors": [{"title": "Not Found", "detail": "community not found", "type": "not_found"}]}

    actions = result.get("actions") or {}
    name = result.get("name") or result.get("display_name") or ""

    created_raw = result.get("created_at")
    created_iso = None
    if isinstance(created_raw, (int, float)) and created_raw > 0:
        from datetime import datetime, timezone
        created_iso = datetime.fromtimestamp(created_raw / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    elif isinstance(created_raw, str):
        created_iso = created_raw

    return {
        "data": {
            "id": result.get("rest_id") or result.get("id_str"),
            "name": name,
            "description": result.get("description"),
            "created_at": created_iso,
            "member_count": result.get("member_count"),
            "moderator_count": result.get("moderator_count"),
            "is_nsfw": result.get("is_nsfw"),
            "join_policy": result.get("join_policy"),
            "invites_policy": result.get("invites_policy"),
            "access": result.get("access"),
            "primary_topic": ((result.get("primary_community_topic") or {}).get("topic_name")),
            "role": result.get("role"),
            "rules": [
                {"id": r.get("rest_id"), "name": r.get("name"), "description": r.get("description")}
                for r in (result.get("rules") or [])
            ],
            "actions": {
                "join_action_result": (actions.get("join_action_result") or {}).get("__typename"),
                "leave_action_result": (actions.get("leave_action_result") or {}).get("__typename"),
                "delete_action_result": (actions.get("delete_action_result") or {}).get("__typename"),
            },
        }
    }


def format_bookmark_folders(gql: dict[str, Any]) -> dict[str, Any]:
    """BookmarkFoldersSlice → {data:[{id,name,...}], meta:{next_token}}."""
    viewer = ((gql or {}).get("data") or {}).get("viewer") or {}
    user_res = ((viewer.get("user_results") or {}).get("result")) or {}
    slice_ = user_res.get("bookmark_collections_slice") or {}
    items = slice_.get("items") or []
    folders = []
    for it in items:
        folders.append({
            "id": it.get("id") or it.get("rest_id"),
            "name": it.get("name"),
            "media_count": it.get("media_count"),
            "tweet_count": it.get("tweet_count"),
            "updated_at": it.get("updated_at"),
            "preview_media_ids": it.get("preview_media_ids"),
        })
    next_token = (slice_.get("slice_info") or {}).get("next_cursor")
    out: dict[str, Any] = {"data": folders, "meta": {"result_count": len(folders)}}
    if next_token:
        out["meta"]["next_token"] = next_token
    return out


def format_birdwatch_note_result(gql: dict[str, Any], create: bool = True) -> dict[str, Any]:
    """BirdwatchCreateNote / DeleteNote / CreateRating result."""
    data = (gql or {}).get("data") or {}
    # try various keys
    for key in ("birdwatchnote_create_v2", "birdwatchnote_delete", "birdwatchnote_rate_v3"):
        node = data.get(key)
        if node:
            if node.get("type") == "BirdwatchError" or node.get("__typename") == "BirdwatchError":
                return {"errors": [{
                    "title": "Birdwatch Error",
                    "detail": node.get("reason") or node.get("error_code") or "unknown",
                    "type": "birdwatch_error",
                }]}
            return {"data": node}
    return {"data": data}


def format_birdwatch_notes_slice(gql: dict[str, Any]) -> dict[str, Any]:
    """BirdwatchFetchContributorNotesSlice."""
    profile = ((gql or {}).get("data") or {}).get("birdwatch_profile_by_alias") or {}
    slice_ = profile.get("notes_slice") or {}
    notes = slice_.get("notes") or []
    out_notes = []
    for n in notes:
        out_notes.append({
            "id": n.get("rest_id") or n.get("id"),
            "tweet_id": (n.get("tweet_results") or {}).get("result", {}).get("rest_id"),
            "created_at": n.get("created_at"),
            "data": n.get("data_v1") or n.get("data"),
            "classification": n.get("classification"),
            "status": n.get("status"),
        })
    next_token = (slice_.get("slice_info") or {}).get("next_cursor")
    out: dict[str, Any] = {"data": out_notes, "meta": {"result_count": len(out_notes)}}
    if next_token:
        out["meta"]["next_token"] = next_token
    return out


def format_birdwatch_batsignal(gql: dict[str, Any]) -> dict[str, Any]:
    """BirdwatchFetchBatSignal."""
    data = (gql or {}).get("data") or {}
    signal = data.get("birdwatchbatsignal") or data.get("birdwatch_eligible_posts") or data
    posts = signal.get("posts") or signal.get("eligible_posts") or []
    return {"data": posts, "meta": {"result_count": len(posts)}}


# ──────────────── DM normalizer ────────────────


def _dm_user_obj(u: dict[str, Any]) -> Optional[dict[str, Any]]:
    """REST 1.1 user → X API v2 user object (subset)."""
    if not u:
        return None
    avatar = u.get("profile_image_url_https")
    default_avatar = u.get("default_profile_image")
    if default_avatar is None and isinstance(avatar, str):
        default_avatar = "default_profile" in avatar
    return {
        "id": str(u.get("id_str") or u.get("id") or ""),
        "name": u.get("name"),
        "username": u.get("screen_name"),
        "created_at": u.get("created_at"),
        "description": u.get("description"),
        "verified": u.get("ext_is_blue_verified") or u.get("verified") or False,
        "protected": u.get("protected", False),
        "profile_image_url": avatar,
        "default_profile_image": bool(default_avatar) if default_avatar is not None else False,
        "relationship": {
            "following": u.get("following"),
            "followed_by": u.get("followed_by"),
            "blocking": u.get("blocking"),
            "muting": u.get("muting"),
        },
        "public_metrics": {
            "followers_count": u.get("followers_count"),
            "following_count": u.get("friends_count"),
            "tweet_count": u.get("statuses_count"),
            "listed_count": u.get("listed_count"),
        },
    }


def _dm_event_to_obj(
    ev: dict[str, Any],
    users: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """
    Convert REST 1.1 DM event → X API v2 dm_events shape.
    Spec v2: {id, event_type, created_at, dm_conversation_id, sender_id, text, attachments?, referenced_tweets?, participant_ids?}

    `users` is the inbox-level users map keyed by user_id (string). When
    provided, MessageCreate events get a non-spec `_sender_follows_owner`
    flag derived from `users[sender_id].followed_by` so consumers can
    enforce mutual/follower-only policies without a second lookup.
    """
    if not ev:
        return None
    et = ev.get("type") or ev.get("event_type")
    msg = ev.get("message_create") or {}
    # REST 1.1 inbox_initial_state.entries: message_data sits directly on the
    # event (entry was {"message": {message_data: {...}}}). For
    # Account Activity API (`message_create.message_data`), keep nested fallback.
    msg_data = ev.get("message_data") or msg.get("message_data") or {}

    raw_conv_id = ev.get("conversation_id") or msg.get("target", {}).get("conversation_id")
    base: dict[str, Any] = {
        "id": str(ev.get("id") or ev.get("event_id") or ""),
        "event_type": _DM_EVENT_TYPE_MAP.get(et, et),
        "created_at": _dm_ts_to_iso(ev.get("created_timestamp") or ev.get("time")),
        "dm_conversation_id": str(raw_conv_id).replace(":", "-") if raw_conv_id else None,
    }

    if et in ("message_create", "Message", "message"):
        sender = msg_data.get("sender_id") or msg.get("sender_id") or ev.get("sender_id")
        raw_text = msg_data.get("text") if msg_data.get("text") is not None else ev.get("text")
        text = raw_text if raw_text is not None else ""
        base.update(
            {
                "event_type": "MessageCreate",
                "sender_id": str(sender) if sender else None,
                "text": text,
            }
        )
        # Tag sender follow status for downstream policy. `followed_by` is
        # 1.1's "this user follows the bot owner". Missing/None → unknown.
        if sender and users:
            sender_obj = users.get(str(sender)) or {}
            s_rel = sender_obj.get("relationship") if isinstance(sender_obj.get("relationship"), dict) else {}
            fb = sender_obj.get("followed_by") if sender_obj.get("followed_by") is not None else s_rel.get("followed_by")
            if fb is True:
                base["_sender_follows_owner"] = True
            elif fb is False:
                base["_sender_follows_owner"] = False
            fw = sender_obj.get("following") if sender_obj.get("following") is not None else s_rel.get("following")
            if fw is True:
                base["_owner_follows_sender"] = True
            elif fw is False:
                base["_owner_follows_sender"] = False
        # entities
        entities = msg_data.get("entities") or {}
        urls_list: list[dict[str, Any]] = [
            {
                "url": u.get("url"),
                "expanded_url": u.get("expanded_url"),
                "display_url": u.get("display_url"),
            }
            for u in (entities.get("urls") or [])
            if isinstance(u, dict)
        ]
        seen_tco = {u.get("url") for u in urls_list if u.get("url")}

        def _add_entity_url(item: Any) -> None:
            if not isinstance(item, dict):
                return
            u_short = item.get("url")
            u_exp = item.get("expanded_url")
            if u_short and u_exp and u_short not in seen_tco:
                seen_tco.add(u_short)
                urls_list.append({
                    "url": u_short,
                    "expanded_url": u_exp,
                    "display_url": item.get("display_url"),
                })

        # attachments (media in DM message_data)
        attach = msg_data.get("attachment") or {}
        media_raw = (
            attach.get("media")
            or attach.get("photo")
            or attach.get("video")
            or attach.get("animated_gif")
            or (msg_data.get("extended_entities") or {}).get("media")
            or entities.get("media")
        )
        media_items = media_raw if isinstance(media_raw, list) else ([media_raw] if isinstance(media_raw, dict) else [])
        att_objs = []
        media_keys = []
        for m_item in media_items:
            if isinstance(m_item, dict):
                _add_entity_url(m_item)
                if m_item.get("id_str") or m_item.get("id"):
                    att_obj = _dm_attachment_obj(m_item)
                    m_v2 = _dm_media_v2_obj(att_obj)
                    att_objs.append(att_obj)
                    media_keys.append(str(m_v2.get("media_key") or m_item.get("id_str") or m_item.get("id")))
        if att_objs:
            base["attachments"] = {"media_keys": media_keys}
            # Surface DL URL + type so consumers can fetch the binary without
            # re-walking includes. `_xapi_attachments` is non-spec; consumers
            # should treat it as best-effort.
            base["_xapi_attachments"] = att_objs
        # quoted/referenced tweet
        if isinstance(attach.get("tweet"), dict):
            tw = attach["tweet"]
            _add_entity_url(tw)
            if isinstance(tw.get("status"), dict):
                _add_entity_url(tw["status"])
            tid_val = tw.get("id") or tw.get("id_str") or (tw.get("status") or {}).get("id_str") or (tw.get("status") or {}).get("id")
            if tid_val:
                base["referenced_tweets"] = [{"type": "quoted", "id": str(tid_val)}]

        if entities or urls_list:
            base["entities"] = {
                "hashtags": [{"tag": h.get("text")} for h in entities.get("hashtags", []) if isinstance(h, dict)],
                "mentions": [
                    {"username": m.get("screen_name"), "id": str(m.get("id_str") or "")}
                    for m in entities.get("user_mentions", [])
                    if isinstance(m, dict)
                ],
                "urls": urls_list,
            }

    elif et in ("conversation_join_events", "ParticipantsJoin", "participants_join"):
        base["event_type"] = "ParticipantsJoin"
        ids = ev.get("participants") or msg.get("participants") or []
        base["participant_ids"] = [str(p.get("user_id") or p) for p in ids]
    elif et in ("conversation_leave_events", "ParticipantsLeave", "participants_leave"):
        base["event_type"] = "ParticipantsLeave"
        ids = ev.get("participants") or msg.get("participants") or []
        base["participant_ids"] = [str(p.get("user_id") or p) for p in ids]
    elif et in ("conversation_name_update", "ConversationNameUpdate"):
        base["event_type"] = "ConversationNameUpdate"
        base["conversation_name"] = (ev.get("conversation_name_update") or {}).get("name")
    elif et in ("conversation_avatar_update", "ConversationAvatarUpdate"):
        base["event_type"] = "ConversationAvatarUpdate"

    return {k: v for k, v in base.items() if v is not None}


_DM_EVENT_TYPE_MAP = {
    "message_create": "MessageCreate",
    "Message": "MessageCreate",
    "message": "MessageCreate",
    "conversation_join_events": "ParticipantsJoin",
    "conversation_leave_events": "ParticipantsLeave",
    "conversation_name_update": "ConversationNameUpdate",
    "conversation_avatar_update": "ConversationAvatarUpdate",
}


def _dm_ts_to_iso(ts: Any) -> Optional[str]:
    """REST 1.1 / GraphQL DM timestamp (ms epoch string/int or ISO string) → ISO 8601."""
    if not ts:
        return None
    if isinstance(ts, str) and "T" in ts and ts.endswith("Z"):
        return ts
    try:
        from datetime import datetime, timezone

        ms = int(ts)
        # Handle seconds vs milliseconds epoch
        if ms < 10_000_000_000:
            ms *= 1000
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"
    except (ValueError, TypeError):
        return str(ts)


def _decode_xchat_thrift_event(b64_str: str, default_conv_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """
    Decode a Base64-encoded Apache Thrift binary `XChatMessageEvent` blob from
    `GetInitialXChatPageQuery` / `GetConversationPageQuery` (`latest_message_events`).

    Thrift field layout in XChat:
      1 (STRING): event_id (Snowflake ID string)
      2 (STRING): request_id / UUID
      3 (STRING): sender_id (User rest_id string)
      4 (STRING): conversation_id ("<uid1>:<uid2>")
      5 (STRING): juicebox JWT token
      6 (STRING): created_timestamp_ms (epoch ms string)
      7 (STRUCT): payload (field 1 = encrypted message struct -> field 100 = E2EE ciphertext bytes)
    """
    if not isinstance(b64_str, str) or len(b64_str) < 16:
        return None
    try:
        import base64
        import struct

        padded = b64_str + "=" * ((4 - len(b64_str) % 4) % 4)
        buf = base64.b64decode(padded)
    except Exception:
        return None

    def _read_val(ftype: int, off: int) -> tuple[Any, int]:
        if off >= len(buf):
            raise ValueError("Thrift buffer underflow")
        if ftype == 2 or ftype == 3:
            return buf[off], off + 1
        if ftype == 4:
            if off + 8 > len(buf):
                raise ValueError("Thrift DOUBLE underflow")
            return struct.unpack(">d", buf[off : off + 8])[0], off + 8
        if ftype == 6:
            if off + 2 > len(buf):
                raise ValueError("Thrift I16 underflow")
            return struct.unpack(">h", buf[off : off + 2])[0], off + 2
        if ftype == 8:
            if off + 4 > len(buf):
                raise ValueError("Thrift I32 underflow")
            return struct.unpack(">i", buf[off : off + 4])[0], off + 4
        if ftype == 10:
            if off + 8 > len(buf):
                raise ValueError("Thrift I64 underflow")
            return struct.unpack(">q", buf[off : off + 8])[0], off + 8
        if ftype == 11:
            if off + 4 > len(buf):
                raise ValueError("Thrift STRING length underflow")
            ln = struct.unpack(">i", buf[off : off + 4])[0]
            off += 4
            if ln < 0 or off + ln > len(buf):
                raise ValueError("Thrift STRING payload out of bounds")
            raw_b = buf[off : off + ln]
            off += ln
            try:
                return raw_b.decode("utf-8"), off
            except UnicodeDecodeError:
                return base64.b64encode(raw_b).decode("ascii"), off
        if ftype == 12:
            return _read_struct(off)
        if ftype == 13:
            if off + 6 > len(buf):
                raise ValueError("Thrift MAP header underflow")
            kt, vt = buf[off], buf[off + 1]
            sz = struct.unpack(">i", buf[off + 2 : off + 6])[0]
            off += 6
            if sz < 0 or sz > 10000:
                raise ValueError("Thrift MAP size out of bounds")
            mp: dict[Any, Any] = {}
            for _ in range(sz):
                k, off = _read_val(kt, off)
                v, off = _read_val(vt, off)
                mp[k] = v
            return mp, off
        if ftype == 14 or ftype == 15:
            if off + 5 > len(buf):
                raise ValueError("Thrift LIST/SET header underflow")
            et = buf[off]
            sz = struct.unpack(">i", buf[off + 1 : off + 5])[0]
            off += 5
            if sz < 0 or sz > 10000:
                raise ValueError("Thrift LIST/SET size out of bounds")
            arr = []
            for _ in range(sz):
                v, off = _read_val(et, off)
                arr.append(v)
            return arr, off
        raise ValueError(f"Unsupported thrift type {ftype}")

    def _read_struct(off: int) -> tuple[dict[int, Any], int]:
        out_f: dict[int, Any] = {}
        while off < len(buf):
            ft = buf[off]
            off += 1
            if ft == 0:
                break
            if off + 2 > len(buf):
                raise ValueError("Thrift field ID underflow")
            fid = struct.unpack(">h", buf[off : off + 2])[0]
            off += 2
            val, off = _read_val(ft, off)
            out_f[fid] = val
        return out_f, off

    try:
        parsed, _ = _read_struct(0)
    except Exception:
        return None

    ev_id = parsed.get(1)
    if not ev_id:
        return None
    sender_id = parsed.get(3)
    conv_id = str(parsed.get(4) or default_conv_id or "").replace(":", "-")
    ts = parsed.get(6)
    payload_struct = parsed.get(7) if isinstance(parsed.get(7), dict) else {}
    msg_struct = payload_struct.get(1) if isinstance(payload_struct.get(1), dict) else {}
    ciphertext_b64 = msg_struct.get(100) if isinstance(msg_struct, dict) else None

    # Field 12 inside payload_struct (7 -> 12) is MarkRead event
    if 12 in payload_struct and not msg_struct:
        return None

    out: dict[str, Any] = {
        "id": str(ev_id),
        "event_type": "MessageCreate",
        "created_at": _dm_ts_to_iso(ts),
        "dm_conversation_id": conv_id or None,
        "sender_id": str(sender_id) if sender_id else None,
        "text": "[XChat E2EE Encrypted Message]" if ciphertext_b64 else None,
        "_xchat_encrypted": bool(ciphertext_b64),
    }
    if ciphertext_b64:
        out["encrypted_text"] = ciphertext_b64
    return {k: v for k, v in out.items() if v is not None}


def _merge_user_obj(existing: Optional[dict[str, Any]], new_obj: dict[str, Any]) -> dict[str, Any]:
    """Merge two user objects without overwriting non-None fields (including nested public_metrics/relationship) with None."""
    if not existing:
        return dict(new_obj)
    merged = dict(existing)
    for k, v in new_obj.items():
        if v is None:
            continue
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            sub = dict(merged[k])
            for sk, sv in v.items():
                if sv is not None:
                    sub[sk] = sv
            merged[k] = sub
        else:
            merged[k] = v
    return merged


def _gql_dm_event_to_obj(
    ev: dict[str, Any],
    default_conv_id: Optional[str] = None,
    users_by_id: Optional[dict[str, dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    """
    Convert GraphQL DM / XChat message or event node → X API v2 dm_events shape.
    Supports:
    - XChat `GetInitialXChatPageQuery` / `GetConversationPageQuery` / `GetMessageEventsPageQuery`
      message event nodes (`id`/`event_id`/`rest_id`, `conversation_id`, `sender_id`/`sender_results`,
      `text`/`content`/`message_data`, `created_at`/`created_timestamp`/`timestamp_ms`)
    - Standard REST-like event nodes embedded in GraphQL responses
    - `DmAllSearchSlice` / `DmGroupSearchSlice` message search items
    """
    if not isinstance(ev, dict) or not ev:
        return None

    # Unwrap nested message wrappers if present
    inner = (
        ev.get("message")
        or ev.get("message_event")
        or ev.get("event")
        or ev.get("dm_event")
        or ev
    )
    if not isinstance(inner, dict):
        inner = ev

    # Extract nested user if present on sender_results / user_results
    for u_key in ("sender_results", "user_results", "sender", "user"):
        u_node = inner.get(u_key) or ev.get(u_key)
        if isinstance(u_node, dict):
            res = u_node.get("result") if "result" in u_node else u_node
            if isinstance(res, dict) and (res.get("rest_id") or res.get("id_str")):
                u_obj = _user_result_to_obj(res) if "rest_id" in res else _dm_user_obj(res)
                if u_obj and u_obj.get("id") and users_by_id is not None:
                    uid_str = str(u_obj["id"])
                    users_by_id[uid_str] = _merge_user_obj(users_by_id.get(uid_str), u_obj)

    # If it looks like a standard REST 1.1 event dict, delegate to _dm_event_to_obj
    if "message_create" in inner or ("message_data" in inner and ("id" in inner or "event_id" in inner)):
        obj = _dm_event_to_obj(
            {
                **inner,
                "type": inner.get("type") or inner.get("event_type") or "message_create",
                "conversation_id": inner.get("conversation_id") or default_conv_id,
            },
            users=users_by_id,
        )
        if obj and obj.get("id"):
            return obj

    ev_id = (
        inner.get("id")
        or inner.get("event_id")
        or inner.get("message_id")
        or inner.get("rest_id")
        or inner.get("sequence_id")
        or ev.get("id")
        or ev.get("rest_id")
    )
    if not ev_id:
        return None

    conv_id = (
        inner.get("conversation_id")
        or inner.get("dm_conversation_id")
        or (inner.get("conversation") or {}).get("conversation_id")
        or (inner.get("conversation") or {}).get("id")
        or ev.get("conversation_id")
        or default_conv_id
    )
    if isinstance(conv_id, str) and ":" in conv_id:
        conv_id = conv_id.replace(":", "-")

    content = inner.get("content") if isinstance(inner.get("content"), dict) else {}
    msg_data = inner.get("message_data") if isinstance(inner.get("message_data"), dict) else {}

    sender_id = (
        inner.get("sender_id")
        or inner.get("sender_rest_id")
        or inner.get("user_id")
        or msg_data.get("sender_id")
        or content.get("sender_id")
        or ((inner.get("sender_results") or {}).get("result") or {}).get("rest_id")
        or (inner.get("sender") or {}).get("id_str")
        or (inner.get("sender") or {}).get("rest_id")
        or (inner.get("sender") or {}).get("id")
    )

    text = (
        inner.get("text")
        or (inner.get("content") if isinstance(inner.get("content"), str) else None)
        or content.get("text")
        or content.get("body")
        or msg_data.get("text")
        or (inner.get("body") if isinstance(inner.get("body"), str) else None)
    )

    ts = (
        inner.get("created_at")
        or inner.get("created_at_ms")
        or inner.get("created_timestamp")
        or inner.get("timestamp_ms")
        or inner.get("timestamp")
        or inner.get("time")
        or msg_data.get("created_at")
        or msg_data.get("time")
        or content.get("created_at")
        or ev.get("created_at")
        or ev.get("created_at_ms")
        or ev.get("created_timestamp")
    )
    if ts is None and str(ev_id).isdigit() and len(str(ev_id)) >= 15:
        try:
            snowflake_ms = (int(str(ev_id)) >> 22) + 1288834974657
            if 1288834974657 < snowflake_ms < 4102444800000:
                ts = snowflake_ms
        except Exception:
            pass

    raw_type = (
        inner.get("event_type")
        or inner.get("type")
        or inner.get("__typename")
        or "MessageCreate"
    )
    event_type = _DM_EVENT_TYPE_MAP.get(raw_type, "MessageCreate" if "Message" in str(raw_type) or text is not None else str(raw_type))

    out: dict[str, Any] = {
        "id": str(ev_id),
        "event_type": event_type,
        "created_at": _dm_ts_to_iso(ts),
        "dm_conversation_id": str(conv_id) if conv_id else None,
        "sender_id": str(sender_id) if sender_id else None,
        "text": text,
    }

    if sender_id and isinstance(users_by_id, dict):
        s_obj = users_by_id.get(str(sender_id))
        if isinstance(s_obj, dict):
            s_rel = s_obj.get("relationship") if isinstance(s_obj.get("relationship"), dict) else {}
            fb = s_obj.get("followed_by") if s_obj.get("followed_by") is not None else s_rel.get("followed_by")
            if fb is True:
                out["_sender_follows_owner"] = True
            elif fb is False:
                out["_sender_follows_owner"] = False
            fw = s_obj.get("following") if s_obj.get("following") is not None else s_rel.get("following")
            if fw is True:
                out["_owner_follows_sender"] = True
            elif fw is False:
                out["_owner_follows_sender"] = False

    # Entities if present
    entities = inner.get("entities") or msg_data.get("entities") or content.get("entities") or {}
    gql_urls: list[dict[str, Any]] = [
        {
            "url": u.get("url"),
            "expanded_url": u.get("expanded_url"),
            "display_url": u.get("display_url"),
        }
        for u in (entities.get("urls") or [])
        if isinstance(u, dict)
    ] if isinstance(entities, dict) else []
    seen_gql_tco = {u.get("url") for u in gql_urls if u.get("url")}

    def _add_gql_url(item: Any) -> None:
        if not isinstance(item, dict):
            return
        u_short = item.get("url")
        u_exp = item.get("expanded_url")
        if u_short and u_exp and u_short not in seen_gql_tco:
            seen_gql_tco.add(u_short)
            gql_urls.append({
                "url": u_short,
                "expanded_url": u_exp,
                "display_url": item.get("display_url"),
            })

    # Media & tweet attachments if present
    attach = inner.get("attachment") or msg_data.get("attachment") or content.get("attachment") or {}
    if isinstance(attach, dict):
        media_raw = (
            attach.get("media")
            or attach.get("photo")
            or attach.get("video")
            or attach.get("animated_gif")
            or (entities.get("media") if isinstance(entities, dict) else None)
        )
        media_items = media_raw if isinstance(media_raw, list) else ([media_raw] if isinstance(media_raw, dict) else [])
        att_objs = []
        media_keys = []
        for m_item in media_items:
            if isinstance(m_item, dict):
                _add_gql_url(m_item)
                if m_item.get("id_str") or m_item.get("id"):
                    att_obj = _dm_attachment_obj(m_item)
                    m_v2 = _dm_media_v2_obj(att_obj)
                    att_objs.append(att_obj)
                    media_keys.append(str(m_v2.get("media_key") or m_item.get("id_str") or m_item.get("id")))
        if att_objs:
            out["attachments"] = {"media_keys": media_keys}
            out["_xapi_attachments"] = att_objs
        if isinstance(attach.get("tweet"), dict):
            tw = attach["tweet"]
            _add_gql_url(tw)
            if isinstance(tw.get("status"), dict):
                _add_gql_url(tw["status"])
            tid_val = tw.get("id") or tw.get("id_str") or tw.get("rest_id") or (tw.get("status") or {}).get("id_str") or (tw.get("status") or {}).get("id")
            if tid_val:
                out["referenced_tweets"] = [{"type": "quoted", "id": str(tid_val)}]

    if (isinstance(entities, dict) and entities) or gql_urls:
        out["entities"] = {
            "hashtags": [{"tag": h.get("text")} for h in (entities.get("hashtags") or []) if isinstance(h, dict)] if isinstance(entities, dict) else [],
            "mentions": [
                {"username": m.get("screen_name"), "id": str(m.get("id_str") or m.get("id") or "")}
                for m in (entities.get("user_mentions") or [])
                if isinstance(m, dict)
            ] if isinstance(entities, dict) else [],
            "urls": gql_urls,
        }

    # Participants if present
    participants = inner.get("participants") or inner.get("participant_ids")
    if isinstance(participants, list) and participants:
        p_ids = []
        for p in participants:
            if isinstance(p, dict):
                uid = p.get("user_id") or p.get("rest_id") or p.get("id") or ((p.get("user_results") or {}).get("result") or {}).get("rest_id")
                if uid:
                    p_ids.append(str(uid))
                u_res = (p.get("user_results") or {}).get("result") or p.get("user")
                if isinstance(u_res, dict) and users_by_id is not None:
                    u_obj = _user_result_to_obj(u_res) if "rest_id" in u_res else _dm_user_obj(u_res)
                    if u_obj and u_obj.get("id"):
                        uid_str = str(u_obj["id"])
                        users_by_id[uid_str] = _merge_user_obj(users_by_id.get(uid_str), u_obj)
            elif p:
                p_ids.append(str(p))
        if p_ids and event_type in ("ParticipantsJoin", "ParticipantsLeave"):
            out["participant_ids"] = p_ids

    return {k: v for k, v in out.items() if v is not None}


def _extract_gql_dm_conversations_and_events(
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], Optional[str], Optional[str]]:
    """
    Walk GraphQL DM / XChat response `data` and extract:
    (events, users_by_id, conversations_by_id, next_token, prev_token).

    Handles:
    - `get_initial_chat_page` (`GetInitialXChatPageQuery`)
    - `get_inbox_page` (`GetInboxPageRequestQuery`)
    - `get_conversation_page` (`GetConversationPageQuery`)
    - `get_message_events_page` (`GetMessageEventsPageQuery`)
    - `get_message_requests_page` (`GetMessageRequestsPageQuery`)
    - `dm_all_search_slice` / `dm_group_search_slice` / `dm_people_search_slice`
    - `viewer.dm_inbox` / generic GraphQL DM containers
    """
    events: list[dict[str, Any]] = []
    users_by_id: dict[str, dict[str, Any]] = {}
    convs_by_id: dict[str, dict[str, Any]] = {}
    next_token: Optional[str] = None
    prev_token: Optional[str] = None

    def _collect_user(u_node: Any) -> None:
        if not isinstance(u_node, dict):
            return
        res = u_node.get("result") if "result" in u_node else u_node
        if not isinstance(res, dict):
            return
        if res.get("rest_id") or res.get("__typename") == "User":
            u_obj = _user_result_to_obj(res)
        elif res.get("id_str") or res.get("screen_name"):
            u_obj = _dm_user_obj(res)
        else:
            u_obj = None
        if u_obj and u_obj.get("id"):
            uid_str = str(u_obj["id"])
            users_by_id[uid_str] = _merge_user_obj(users_by_id.get(uid_str), u_obj)

    def _collect_conv(c: dict[str, Any]) -> Optional[str]:
        if not isinstance(c, dict):
            return None
        detail = c.get("conversation_detail") if isinstance(c.get("conversation_detail"), dict) else {}
        cid = str(
            c.get("conversation_id")
            or detail.get("conversation_id")
            or c.get("id")
            or c.get("rest_id")
            or ""
        )
        if ":" in cid:
            cid = cid.replace(":", "-")
        if not cid:
            return None

        parts_raw = (
            c.get("participants")
            or detail.get("participants_results")
            or c.get("participants_results")
            or c.get("members")
            or c.get("users")
            or []
        )
        part_ids: list[str] = []
        if isinstance(parts_raw, list):
            for p in parts_raw:
                if isinstance(p, dict):
                    _collect_user(p.get("user_results") or p.get("result") or p.get("user") or p)
                    uid = (
                        p.get("user_id")
                        or p.get("rest_id")
                        or p.get("id_str")
                        or p.get("id")
                        or ((p.get("user_results") or {}).get("result") or {}).get("rest_id")
                        or (p.get("result") or {}).get("rest_id")
                    )
                    if uid:
                        part_ids.append(str(uid))
                elif p:
                    part_ids.append(str(p))

        ctype_raw = str(
            c.get("type")
            or c.get("conversation_type")
            or detail.get("__typename")
            or ""
        ).upper()
        ctype = "Group" if "GROUP" in ctype_raw or len(part_ids) > 2 else "OneToOne"

        # Ensure both user IDs in a OneToOne `<uid1>-<uid2>` conversation are in participant_ids
        if ctype == "OneToOne" and "-" in cid:
            for p_uid in cid.split("-"):
                if p_uid.isdigit() and p_uid not in part_ids:
                    part_ids.append(p_uid)

        existing_conv = convs_by_id.get(cid) or {}
        merged_parts = list(existing_conv.get("participant_ids") or [])
        for p_uid in part_ids:
            if p_uid not in merged_parts:
                merged_parts.append(p_uid)
        merged_ctype = "Group" if existing_conv.get("type") == "Group" or ctype == "Group" or len(merged_parts) > 2 else "OneToOne"
        convs_by_id[cid] = {
            "id": cid,
            "type": merged_ctype,
            "participant_ids": merged_parts,
            "name": c.get("name") or c.get("title") or detail.get("name") or existing_conv.get("name"),
            "trusted": c.get("trusted") if c.get("trusted") is not None else (detail.get("trusted") if detail.get("trusted") is not None else existing_conv.get("trusted")),
            "muted": c.get("muted") if c.get("muted") is not None else (detail.get("is_muted") if detail.get("is_muted") is not None else existing_conv.get("muted")),
            "last_read_event_id": c.get("last_read_event_id") or detail.get("last_read_event_id") or existing_conv.get("last_read_event_id"),
        }
        convs_by_id[cid] = {k: v for k, v in convs_by_id[cid].items() if v is not None}

        # Collect messages / latest_message inside conversation node
        conv_msgs = (
            c.get("messages")
            or c.get("latest_message_events")
            or c.get("message_events")
            or c.get("events")
            or c.get("items")
            or []
        )
        if isinstance(conv_msgs, dict):
            conv_msgs = conv_msgs.get("items") or conv_msgs.get("edges") or conv_msgs.get("entries") or []
        if isinstance(conv_msgs, list):
            for m in conv_msgs:
                if isinstance(m, str):
                    ev_obj = _decode_xchat_thrift_event(m, default_conv_id=cid)
                    if ev_obj:
                        events.append(ev_obj)
                    continue
                node = m.get("node") if isinstance(m, dict) and "node" in m else m
                if isinstance(node, dict):
                    ev_obj = _gql_dm_event_to_obj(node, default_conv_id=cid, users_by_id=users_by_id)
                    if ev_obj:
                        events.append(ev_obj)

        for single_key in (
            "latest_message",
            "last_message",
            "last_message_event",
            "latest_notifiable_message_create_event",
            "snippet",
        ):
            lm = c.get(single_key)
            if isinstance(lm, str):
                ev_obj = _decode_xchat_thrift_event(lm, default_conv_id=cid)
                if ev_obj:
                    events.append(ev_obj)
            elif isinstance(lm, dict):
                ev_obj = _gql_dm_event_to_obj(lm, default_conv_id=cid, users_by_id=users_by_id)
                if ev_obj:
                    events.append(ev_obj)

        return cid

    # Inspect known top-level GraphQL DM/XChat containers
    containers: list[dict[str, Any]] = []
    for key in (
        "get_initial_chat_page",
        "get_inbox_page",
        "get_conversation_page",
        "get_message_events_page",
        "get_message_requests_page",
        "get_message_events_by_sequence_id",
        "dm_all_search_slice",
        "dm_group_search_slice",
        "dm_people_search_slice",
        "xchat_send_create_message_event",
    ):
        node = data.get(key)
        if isinstance(node, dict):
            containers.append(node)

    viewer = data.get("viewer")
    if isinstance(viewer, dict):
        for vkey in ("dm_inbox", "chat_inbox", "inbox"):
            if isinstance(viewer.get(vkey), dict):
                containers.append(viewer[vkey])

    if not containers and isinstance(data, dict):
        containers.append(data)

    for container in containers:
        # 1. Users list / map
        users_node = container.get("users") or container.get("user_results")
        if isinstance(users_node, dict):
            for u in users_node.values():
                _collect_user(u)
        elif isinstance(users_node, list):
            for u in users_node:
                _collect_user(u)

        # 2. Conversations list / map / single
        conv_single = container.get("conversation")
        default_cid: Optional[str] = None
        if isinstance(conv_single, dict):
            default_cid = _collect_conv(conv_single)
        elif isinstance(container.get("conversation_id"), str):
            default_cid = container["conversation_id"].replace(":", "-")

        convs_node = (
            container.get("conversations")
            or container.get("inbox_conversations")
            or container.get("conversation_slice")
        )
        if isinstance(convs_node, dict):
            if "items" in convs_node and isinstance(convs_node["items"], list):
                for c in convs_node["items"]:
                    if isinstance(c, dict):
                        _collect_conv(c)
                s_info = convs_node.get("slice_info") or convs_node.get("page_info") or {}
                if isinstance(s_info, dict):
                    next_token = next_token or s_info.get("next_cursor") or s_info.get("end_cursor")
            else:
                for c in convs_node.values():
                    if isinstance(c, dict):
                        _collect_conv(c)
        elif isinstance(convs_node, list):
            for c in convs_node:
                if isinstance(c, dict):
                    _collect_conv(c)

        # 3. Messages / events list / slice
        for msg_key in ("messages", "message_events", "events", "entries", "items"):
            msgs_node = container.get(msg_key)
            if isinstance(msgs_node, dict):
                s_info = msgs_node.get("slice_info") or msgs_node.get("page_info") or {}
                if isinstance(s_info, dict):
                    next_token = next_token or s_info.get("next_cursor") or s_info.get("end_cursor")
                    prev_token = prev_token or s_info.get("previous_cursor") or s_info.get("start_cursor")
                msgs_list = msgs_node.get("items") or msgs_node.get("edges") or msgs_node.get("entries") or []
            elif isinstance(msgs_node, list):
                msgs_list = msgs_node
            else:
                msgs_list = []

            for item in msgs_list:
                if isinstance(item, str):
                    ev_obj = _decode_xchat_thrift_event(item, default_conv_id=default_cid)
                    if ev_obj:
                        events.append(ev_obj)
                    continue
                if not isinstance(item, dict):
                    continue
                node = item.get("node") if "node" in item and isinstance(item["node"], dict) else item
                # XChatGetInboxPageConversationData has `conversation_detail` + `latest_message_events`
                if "conversation_detail" in node or node.get("__typename") == "XChatGetInboxPageConversationData":
                    _collect_conv(node)
                    continue
                # Search slice items may wrap message/conversation/user
                if "dm_convo_search_Metadata" in node or "conversation" in node:
                    if isinstance(node.get("conversation"), dict):
                        _collect_conv(node["conversation"])
                if "user_results" in node or "user" in node:
                    _collect_user(node.get("user_results") or node.get("user"))
                ev_obj = _gql_dm_event_to_obj(node, default_conv_id=default_cid, users_by_id=users_by_id)
                if ev_obj:
                    events.append(ev_obj)

        # 4. Cursors / pagination
        for cur_key in ("inboxCursor", "next_cursor", "cursor", "continue_cursor", "bottom_cursor"):
            c_val = container.get(cur_key)
            if isinstance(c_val, dict):
                c_val = c_val.get("cursor_id") or c_val.get("value") or c_val.get("next_cursor")
            if isinstance(c_val, str) and c_val and not next_token:
                next_token = c_val

        s_info = container.get("slice_info") or container.get("page_info") or {}
        if isinstance(s_info, dict):
            next_token = next_token or s_info.get("next_cursor") or s_info.get("end_cursor")
            prev_token = prev_token or s_info.get("previous_cursor") or s_info.get("start_cursor")

    return events, users_by_id, convs_by_id, next_token, prev_token


def _dm_media_v2_obj(a: dict[str, Any]) -> dict[str, Any]:
    """Convert an `_xapi_attachments` item into an official X API v2 `includes.media` object."""
    m_id = str(a.get("media_id") or "")
    kind = a.get("kind") or "photo"
    prefix = "3" if kind == "photo" else ("7" if kind == "video" else "16")
    media_key = m_id if "_" in m_id else (f"{prefix}_{m_id}" if m_id else None)
    out: dict[str, Any] = {
        "media_key": media_key or m_id,
        "id": m_id or None,
        "type": kind,
        "url": a.get("url"),
        "preview_image_url": a.get("preview_image_url") or (a.get("url") if kind == "photo" else None),
        "width": a.get("width"),
        "height": a.get("height"),
        "duration_ms": a.get("duration_ms"),
    }
    return {k: v for k, v in out.items() if v is not None}


def format_dm_events(
    payload: dict[str, Any],
    event_types: Optional[str] = None,
    dm_event_fields: Optional[str] = None,
    expansions: Optional[str] = None,
    max_results: Optional[int] = None,
) -> dict[str, Any]:
    """
    Format DM response (supports BOTH GraphQL DM/XChat and REST 1.1 DM shapes) → official X API v2 shape:
      {
        "data": [dm_event_obj, ...],
        "includes": {"users": [...], "media": [...], "tweets": [...], "conversations": [...]},
        "meta": {"result_count": N, "next_token": ..., "previous_token": ...}
      }
    """
    if not isinstance(payload, dict) or not payload:
        return {"data": [], "meta": {"result_count": 0}}

    # Check if this is a GraphQL response (has "data" key or GraphQL operation keys)
    gql_data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    is_gql = gql_data is not None or any(
        k in payload
        for k in (
            "get_initial_chat_page",
            "get_inbox_page",
            "get_conversation_page",
            "get_message_events_page",
            "get_message_requests_page",
            "dm_all_search_slice",
            "dm_group_search_slice",
            "dm_people_search_slice",
        )
    )

    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    users_map: dict[str, dict[str, Any]] = {}
    convs_map: dict[str, dict[str, Any]] = {}
    media_map: dict[str, dict[str, Any]] = {}
    tweets_map: dict[str, dict[str, Any]] = {}
    next_token: Optional[str] = None
    prev_token: Optional[str] = None

    if is_gql:
        target_data = gql_data if gql_data is not None else payload
        gql_events, gql_users, gql_convs, next_token, prev_token = _extract_gql_dm_conversations_and_events(target_data)
        for ev in gql_events:
            eid = ev.get("id")
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                events.append(ev)
        users_map.update(gql_users)
        convs_map.update(gql_convs)

    # Also support REST 1.1 DM sections (either standalone or merged with GraphQL)
    sections = [
        payload.get("inbox_initial_state"),
        payload.get("user_events"),
        payload.get("conversation_timeline"),
        payload,
    ]
    inbox_timelines = (payload.get("inbox_initial_state") or {}).get("inbox_timelines") or {}
    for tl in inbox_timelines.values():
        if isinstance(tl, dict):
            sections.append(tl)

    entries: list[dict] = []
    raw_users: dict[str, Any] = {}
    raw_convs: dict[str, Any] = {}

    for sec in sections:
        if not isinstance(sec, dict):
            continue
        sec_entries = sec.get("entries")
        if isinstance(sec_entries, list):
            entries.extend(sec_entries)
        if isinstance(sec.get("users"), dict):
            raw_users.update(sec["users"])
        if isinstance(sec.get("conversations"), dict):
            raw_convs.update(sec["conversations"])
        if not next_token:
            next_token = sec.get("min_entry_id") or sec.get("cursor")
        if not prev_token:
            prev_token = sec.get("max_entry_id")

    for e in entries:
        if not isinstance(e, dict):
            continue
        for kind, body in e.items():
            if not isinstance(body, dict):
                continue
            ev_input = {**body, "type": body.get("type") or kind}
            obj = _dm_event_to_obj(ev_input, users=raw_users)
            if obj and obj.get("id"):
                if obj["id"] not in seen_ids:
                    seen_ids.add(obj["id"])
                    events.append(obj)
                else:
                    for idx_ev, existing_ev in enumerate(events):
                        if existing_ev.get("id") == obj["id"] and (
                            existing_ev.get("_xchat_encrypted")
                            or not existing_ev.get("text")
                            or (obj.get("_xapi_attachments") and not existing_ev.get("_xapi_attachments"))
                            or (obj.get("referenced_tweets") and not existing_ev.get("referenced_tweets"))
                            or (obj.get("entities") and not existing_ev.get("entities"))
                        ):
                            merged_ev = {**existing_ev, **obj}
                            if not obj.get("_xchat_encrypted"):
                                merged_ev.pop("_xchat_encrypted", None)
                                merged_ev.pop("encrypted_text", None)
                            events[idx_ev] = merged_ev
                            break
            # Extract quoted/shared tweet for includes.tweets if present in attachment
            msg_data = body.get("message_data") or (body.get("message_create") or {}).get("message_data") or {}
            tw_attach = (msg_data.get("attachment") or {}).get("tweet") or {}
            tw_status = tw_attach.get("status")
            if isinstance(tw_status, dict) and (tw_status.get("id_str") or tw_status.get("id")):
                tid = str(tw_status.get("id_str") or tw_status.get("id"))
                tweets_map[tid] = {
                    "id": tid,
                    "text": tw_status.get("full_text") or tw_status.get("text"),
                    "author_id": str((tw_status.get("user") or {}).get("id_str") or ""),
                    "created_at": tw_status.get("created_at"),
                }

    for uid, u in raw_users.items():
        if isinstance(u, dict):
            uo = _dm_user_obj(u)
            if uo and uo.get("id"):
                uid_str = str(uo["id"])
                users_map[uid_str] = _merge_user_obj(users_map.get(uid_str), uo)

    for cid, c in raw_convs.items():
        if not isinstance(c, dict):
            continue
        norm_cid = str(c.get("conversation_id") or cid).replace(":", "-")
        parts = c.get("participants") or []
        rest_part_ids = [str(p.get("user_id")) for p in parts if isinstance(p, dict) and p.get("user_id")]
        existing_conv = convs_map.get(norm_cid) or {}
        merged_parts = list(dict.fromkeys((existing_conv.get("participant_ids") or []) + rest_part_ids))
        ctype = "Group" if c.get("type") == "GROUP_DM" or existing_conv.get("type") == "Group" else "OneToOne"
        if ctype == "OneToOne" and "-" in norm_cid:
            for p_uid in norm_cid.split("-"):
                if p_uid.isdigit() and p_uid not in merged_parts:
                    merged_parts.append(p_uid)
        merged_conv = {
            "id": norm_cid,
            "type": ctype,
            "participant_ids": merged_parts,
            "name": c.get("name") or existing_conv.get("name"),
            "trusted": c.get("trusted") if c.get("trusted") is not None else existing_conv.get("trusted"),
            "muted": c.get("muted") if c.get("muted") is not None else existing_conv.get("muted"),
            "last_read_event_id": c.get("last_read_event_id") or existing_conv.get("last_read_event_id"),
        }
        convs_map[norm_cid] = {k: v for k, v in merged_conv.items() if v is not None}

    # Populate participant_ids on events from conversation map & collect includes.media
    for ev in events:
        cid = ev.get("dm_conversation_id")
        if cid and "participant_ids" not in ev:
            if cid in convs_map and convs_map[cid].get("participant_ids"):
                ev["participant_ids"] = convs_map[cid]["participant_ids"]
            elif "-" in cid and all(p.isdigit() for p in cid.split("-")):
                ev["participant_ids"] = cid.split("-")
        for att in ev.get("_xapi_attachments") or []:
            if isinstance(att, dict) and att.get("media_id"):
                m_v2 = _dm_media_v2_obj(att)
                m_id = str(att["media_id"])
                media_map[m_id] = m_v2

    # Optional event_types filter (e.g. "MessageCreate,ParticipantsJoin")
    if event_types:
        allowed_types = {t.strip() for t in event_types.split(",") if t.strip()}
        if allowed_types:
            events = [e for e in events if e.get("event_type") in allowed_types]

    # Sort events newest-first by created_at (ISO 8601 UTC) then Snowflake id
    events.sort(
        key=lambda x: (str(x.get("created_at") or ""), int(x["id"]) if str(x.get("id", "")).isdigit() else 0),
        reverse=True,
    )

    if max_results and max_results > 0 and len(events) > max_results:
        events = events[:max_results]
        if events and events[-1].get("id"):
            next_token = str(events[-1]["id"])

    out: dict[str, Any] = {
        "data": events,
        "meta": {"result_count": len(events)},
    }
    if next_token:
        out["meta"]["next_token"] = str(next_token)
    if prev_token:
        out["meta"]["previous_token"] = str(prev_token)
    if users_map or convs_map or media_map or tweets_map:
        out["includes"] = {}
        if users_map:
            out["includes"]["users"] = list(users_map.values())
        if media_map:
            out["includes"]["media"] = list(media_map.values())
        if tweets_map:
            out["includes"]["tweets"] = list(tweets_map.values())
        if convs_map:
            out["includes"]["conversations"] = list(convs_map.values())
    return out


def format_dm_conversations(payload: dict[str, Any], max_results: Optional[int] = None) -> dict[str, Any]:
    """
    Format GraphQL / REST DM inbox response into a conversation-centric X API v2 list:
      {
        "data": [conversation_obj, ...],
        "includes": {"users": [...], "dm_events": [...]},
        "meta": {"result_count": N, "next_token": ...}
      }
    """
    formatted = format_dm_events(payload)
    includes = formatted.get("includes") or {}
    convs = includes.get("conversations") or []
    events = formatted.get("data") or []
    users = includes.get("users") or []

    # Attach latest message preview to each conversation if available
    latest_by_conv: dict[str, dict[str, Any]] = {}
    for ev in events:
        cid = ev.get("dm_conversation_id")
        if cid and cid not in latest_by_conv:
            latest_by_conv[cid] = ev

    conv_list: list[dict[str, Any]] = []
    for c in convs:
        c_copy = dict(c)
        cid = c_copy.get("id")
        if cid and cid in latest_by_conv:
            c_copy["last_message_event"] = latest_by_conv[cid]
        conv_list.append(c_copy)

    # Sort conversations newest-first by created_at (ISO 8601 UTC) then Snowflake id
    def _conv_sort_key(c_obj: dict[str, Any]) -> tuple[str, int]:
        lme = c_obj.get("last_message_event") or {}
        eid = str(lme.get("id") or c_obj.get("last_read_event_id") or "")
        return (str(lme.get("created_at") or ""), int(eid) if eid.isdigit() else 0)

    conv_list.sort(key=_conv_sort_key, reverse=True)

    if max_results and max_results > 0 and len(conv_list) > max_results:
        conv_list = conv_list[:max_results]

    out: dict[str, Any] = {
        "data": conv_list,
        "meta": {
            "result_count": len(conv_list),
            **({"next_token": formatted["meta"]["next_token"]} if formatted.get("meta", {}).get("next_token") else {}),
        },
    }
    inc_out: dict[str, Any] = {}
    if users:
        inc_out["users"] = users
    if events:
        inc_out["dm_events"] = events
    if inc_out:
        out["includes"] = inc_out
    return out


def format_public_keys(gql: dict[str, Any]) -> dict[str, Any]:
    """Format GraphQL `GetPublicKeys` (`data.user_results_by_rest_ids`) → X API v2 shape."""
    data = (gql or {}).get("data") or {}
    results = data.get("user_results_by_rest_ids") or []
    items: list[dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        res = r.get("result") if "result" in r else r
        if not isinstance(res, dict):
            continue
        uid = res.get("rest_id") or res.get("id")
        keys = res.get("public_keys") or res.get("encryption_public_keys") or res.get("chat_public_keys") or []
        entry: dict[str, Any] = {
            "user_id": str(uid) if uid else None,
            "public_keys": keys,
        }
        if "has_juicebox_secret" in res:
            entry["has_juicebox_secret"] = res.get("has_juicebox_secret")
        if "juicebox_token" in res:
            entry["juicebox_token"] = res.get("juicebox_token")
        items.append({k: v for k, v in entry.items() if v is not None})
    return {"data": items, "meta": {"result_count": len(items)}}


def format_dm_send_result(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Format response dm/new2.json (single message create) → v2 send DM result.
    """
    ev = (payload or {}).get("event") or {}
    if ev:
        obj = _dm_event_to_obj({**ev, "type": ev.get("type") or "message_create"})
        if obj:
            return {"data": {"dm_conversation_id": obj.get("dm_conversation_id"), "dm_event_id": obj["id"]}}
    # fallback shapes: dm/new2.json {entries:[{message:{...}}]} atau
    # {user_events:{entries:[{message_create:{...}}]}}
    entries = list((payload or {}).get("entries") or [])
    entries.extend(((payload or {}).get("user_events") or {}).get("entries") or [])
    for e in entries:
        if not isinstance(e, dict):
            continue
        for k, v in e.items():
            if k in ("message", "message_create", "ParticipantInitialize", "join_conversation") and isinstance(v, dict):
                obj = _dm_event_to_obj({**v, "type": k})
                if obj and obj.get("id"):
                    return {"data": {"dm_conversation_id": obj.get("dm_conversation_id"), "dm_event_id": obj["id"]}}
    for e in entries:
        if not isinstance(e, dict):
            continue
        for k, v in e.items():
            if not isinstance(v, dict):
                continue
            obj = _dm_event_to_obj({**v, "type": k})
            if obj and obj.get("id"):
                return {"data": {"dm_conversation_id": obj.get("dm_conversation_id"), "dm_event_id": obj["id"]}}
    return {"data": payload}
