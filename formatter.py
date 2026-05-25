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
    avatar = (user_result.get("avatar") or {}).get("image_url_https") or legacy.get(
        "profile_image_url_https"
    )
    location = (user_result.get("location") or {}).get("location") or legacy.get("location")

    return {
        "id": user_result.get("rest_id"),
        "name": core.get("name") or legacy.get("name"),
        "username": core.get("screen_name") or legacy.get("screen_name"),
        "created_at": core.get("created_at") or legacy.get("created_at"),
        "description": legacy.get("description"),
        "location": location,
        "url": legacy.get("url"),
        "verified": user_result.get("is_blue_verified") or legacy.get("verified") or False,
        "protected": legacy.get("protected", False),
        "profile_image_url": avatar,
        "public_metrics": {
            "followers_count": legacy.get("followers_count"),
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
    return {
        "media_key": m.get("media_key"),
        "type": m.get("type"),
        "url": m.get("media_url_https"),
        "preview_image_url": m.get("media_url_https"),
        "width": (m.get("original_info") or {}).get("width"),
        "height": (m.get("original_info") or {}).get("height"),
        "alt_text": m.get("ext_alt_text"),
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
    if kind == "photo" and url:
        # X serves DM photos at media_url_https; format is in `format` field
        # (jpg|png|gif|webp). MIME is best-guessed from extension.
        ext = (url.rsplit(".", 1)[-1] or "").lower().split("?", 1)[0]
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp"}.get(ext) or "image/jpeg"
    if isinstance(m.get("size"), int):
        byte_size = m.get("size")

    return {
        "kind": kind,
        "mime": mime,
        "url": url,
        "width": width,
        "height": height,
        "duration_ms": duration_ms,
        "byte_size": byte_size,
        "media_id": str(m.get("id_str") or m.get("id") or ""),
    }


def format_tweet(gql: dict[str, Any]) -> dict[str, Any]:
    """Format TweetResultByRestId."""
    tw = (gql or {}).get("data", {}).get("tweetResult", {}).get("result", {})
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
        if qa and qa["id"] not in {u["id"] for u in includes["users"]}:
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
    return {
        "id": str(u.get("id_str") or u.get("id") or ""),
        "name": u.get("name"),
        "username": u.get("screen_name"),
        "created_at": u.get("created_at"),
        "description": u.get("description"),
        "verified": u.get("ext_is_blue_verified") or u.get("verified") or False,
        "protected": u.get("protected", False),
        "profile_image_url": u.get("profile_image_url_https"),
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

    base: dict[str, Any] = {
        "id": str(ev.get("id") or ev.get("event_id") or ""),
        "event_type": _DM_EVENT_TYPE_MAP.get(et, et),
        "created_at": _dm_ts_to_iso(ev.get("created_timestamp") or ev.get("time")),
        "dm_conversation_id": ev.get("conversation_id") or msg.get("target", {}).get("conversation_id"),
    }

    if et in ("message_create", "Message", "message"):
        sender = msg_data.get("sender_id") or msg.get("sender_id") or ev.get("sender_id")
        text = msg_data.get("text") or ev.get("text")
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
            fb = sender_obj.get("followed_by")
            if fb is True:
                base["_sender_follows_owner"] = True
            elif fb is False:
                base["_sender_follows_owner"] = False
        # entities
        entities = msg_data.get("entities") or {}
        if entities:
            base["entities"] = {
                "hashtags": [{"tag": h.get("text")} for h in entities.get("hashtags", [])],
                "mentions": [
                    {"username": m.get("screen_name"), "id": str(m.get("id_str") or "")}
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
            }
        # attachments (media in DM message_data)
        attach = msg_data.get("attachment") or {}
        media = attach.get("media") or attach.get("photo") or attach.get("video")
        if media and media.get("id_str"):
            base["attachments"] = {"media_keys": [str(media["id_str"])]}
            # Surface DL URL + type so consumers can fetch the binary without
            # re-walking includes. `_xapi_attachments` is non-spec; consumers
            # should treat it as best-effort.
            base["_xapi_attachments"] = [_dm_attachment_obj(media)]
        # quoted/referenced tweet
        if attach.get("tweet"):
            tw = attach["tweet"]
            base["referenced_tweets"] = [{"type": "quoted", "id": str(tw.get("id") or "")}]

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
    """REST 1.1 dm timestamp (ms epoch string) → ISO 8601."""
    if not ts:
        return None
    try:
        from datetime import datetime, timezone

        ms = int(ts)
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except (ValueError, TypeError):
        return str(ts)


def format_dm_events(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Format REST 1.1 dm/user_updates atau dm/conversation/{id} → v2 dm_events shape.

    Sumber kemungkinan:
      - inbox_initial_state.entries (user_updates)
      - conversation_timeline.entries (conversation/{id})
      - inbox_timeline (dm/inbox_timeline/{trusted,untrusted}.json)
    """
    data: list[dict[str, Any]] = []
    users: dict[str, dict] = {}
    convs: dict[str, dict] = {}

    inbox = (
        (payload or {}).get("inbox_initial_state")
        or (payload or {}).get("user_events")
        or (payload or {}).get("conversation_timeline")
        or (payload or {}).get("inbox_timeline")
        or {}
    )

    raw_users_src = inbox.get("users") or {}

    for ev in inbox.get("entries", []) or []:
        for k, v in ev.items():
            obj = _dm_event_to_obj({**v, "type": k}, users=raw_users_src)
            if obj:
                data.append(obj)

    for uid, u in (raw_users_src or {}).items():
        uo = _dm_user_obj(u)
        if uo and uo["id"]:
            users[uo["id"]] = uo

    raw_convs = inbox.get("conversations") or {}
    for cid, conv in (raw_convs or {}).items():
        convs[cid] = {
            "id": cid,
            "type": conv.get("type"),
            "name": conv.get("name"),
            "participant_ids": [str(p.get("user_id")) for p in conv.get("participants", [])],
            "created_at": _dm_ts_to_iso(conv.get("create_time")),
            "last_read_event_id": conv.get("last_read_event_id"),
        }

    meta: dict[str, Any] = {"result_count": len(data)}
    cursor = inbox.get("min_entry_id") or inbox.get("cursor")
    if cursor:
        meta["next_token"] = str(cursor)

    out: dict[str, Any] = {"data": data, "meta": meta}
    includes: dict[str, Any] = {}
    if users:
        includes["users"] = list(users.values())
    if convs:
        includes["dm_conversations"] = list(convs.values())
    if includes:
        out["includes"] = includes
    return out


def format_dm_send_result(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Format response dm/new2.json (single message create) → v2 send DM result.
    """
    ev = (payload or {}).get("event") or {}
    if ev:
        obj = _dm_event_to_obj({**ev, "type": ev.get("type") or "message_create"})
        if obj:
            return {"data": {"dm_conversation_id": obj.get("dm_conversation_id"), "dm_event_id": obj["id"]}}
    # fallback shape
    entries = ((payload or {}).get("user_events") or {}).get("entries") or []
    for e in entries:
        for k, v in e.items():
            obj = _dm_event_to_obj({**v, "type": k})
            if obj and obj.get("id"):
                return {"data": {"dm_conversation_id": obj.get("dm_conversation_id"), "dm_event_id": obj["id"]}}
    return {"data": payload}
