# Xapi endpoint catalog

Base URL: `http://127.0.0.1:8000` (`XAPI_BASE_URL`). Auth: `Authorization: Bearer <auth_token>`.
All `/2/*` routes accept `raw=1` for the unfiltered upstream payload (may be disabled).
`/openapi.json` is authoritative if this table drifts.

Common query params: `max_results` (1–100, default 20) and a cursor — usually
`pagination_token`, but search uses `next_token`, and tweet detail/affiliates use `cursor`.

## Users

| Method | Path | Notes |
|---|---|---|
| GET | `/2/users/me` | Authenticated user |
| GET | `/2/users/by/username/{username}` | Handle → user (max 15 chars) |
| GET | `/2/users/by?usernames=a,b` | Bulk by handle, max 100 |
| GET | `/2/users?ids=1,2` | Bulk by ID, max 100 |
| GET | `/2/users/{user_id}` | Single user (Playwright, CF-gated) |
| GET | `/2/users/search?query=` | People search (Playwright) |
| GET | `/2/users/{user_id}/tweets` | `max_results`, `pagination_token` |
| GET | `/2/users/{user_id}/tweets/replies` | Replies tab |
| GET | `/2/users/{user_id}/mentions` | Mentions |
| GET | `/2/users/{user_id}/media` | Media tab |
| GET | `/2/users/{user_id}/liked_tweets` | Likes (own only) |
| GET | `/2/users/{user_id}/followers` | Followers |
| GET | `/2/users/{user_id}/following` | Following |
| GET | `/2/users/{user_id}/blocking` | Own blocking list |
| GET | `/2/users/{user_id}/muting` | Own muting list |
| GET | `/2/users/{user_id}/affiliates` | Premium business team (`count`, `cursor`) |
| GET | `/2/users/reposts_of_me` | Reposts of the authenticated user |
| GET | `/2/users/{user_id}/public_keys` | 501 stub |
| POST | `/2/users/{user_id}/public_keys` | 501 stub |
| GET | `/2/users/public_keys` | 501 stub |
| POST | `/2/users/{user_id}/likes` | Body `{"tweet_id":"..."}` |
| DELETE | `/2/users/{user_id}/likes/{tweet_id}` | Unlike |
| POST | `/2/users/{user_id}/retweets` | Body `{"tweet_id":"..."}` |
| DELETE | `/2/users/{user_id}/retweets/{tweet_id}` | Unretweet |
| DELETE | `/2/users/{user_id}/retweets/by/source_tweet_id/{tweet_id}` | Unretweet (alt) |
| POST | `/2/users/{user_id}/following` | Body `{"target_user_id":"..."}` |
| DELETE | `/2/users/{source_user_id}/following/{target_user_id}` | Unfollow |
| POST | `/2/users/{user_id}/muting` | Body `{"target_user_id":"..."}` |
| DELETE | `/2/users/{source_user_id}/muting/{target_user_id}` | Unmute |
| POST | `/2/users/{user_id}/blocking` | Body `{"target_user_id":"..."}` |
| DELETE | `/2/users/{source_user_id}/blocking/{target_user_id}` | Unblock |
| POST | `/2/users/{user_id}/pinned_tweets` | Body `{"tweet_id":"..."}` |
| DELETE | `/2/users/{user_id}/pinned_tweets/{tweet_id}` | Unpin |

## Tweets

| Method | Path | Notes |
|---|---|---|
| GET | `/2/tweets?ids=1,2` | Bulk lookup, max 100 |
| GET | `/2/tweets/{tweet_id}` | Single tweet |
| GET | `/2/tweets/{tweet_id}/detail` | Thread + replies (`cursor`) |
| GET | `/2/tweets/search/recent?query=` | `type=Latest\|Top\|People\|Media`, cursor `next_token` |
| GET | `/2/tweets/{tweet_id}/liking_users` | Likers |
| GET | `/2/tweets/{tweet_id}/retweeted_by` | Retweeters |
| GET | `/2/tweets/{tweet_id}/retweets` | Retweets list |
| GET | `/2/tweets/{tweet_id}/quote_tweets` | Quote tweets |
| POST | `/2/tweets` | Body below |
| DELETE | `/2/tweets/{tweet_id}` | Delete own tweet |
| PUT | `/2/tweets/{tweet_id}/hidden` | Hide/unhide a reply |

`POST /2/tweets` body:

```json
{
  "text": "required, max 4000 chars",
  "reply_to": "optional tweet id",
  "quote_tweet_id": "optional tweet id",
  "media_ids": ["optional", "up to 4"]
}
```

## Timelines

| Method | Path | Notes |
|---|---|---|
| GET | `/2/home_timeline` | For You, `max_results`, `pagination_token` |
| GET | `/2/users/{user_id}/timelines/reverse_chronological` | Following timeline |

## Lists

| Method | Path | Notes |
|---|---|---|
| POST | `/2/lists` | Body `{name, description?, is_private?}` |
| PUT | `/2/lists` | Body `{list_id, name?, description?, is_private?}` |
| PUT | `/2/lists/{list_id}` | Body `{name?, description?, is_private?}` |
| DELETE | `/2/lists/{list_id}` | Delete list |
| GET | `/2/lists/{list_id}` | List detail |
| GET | `/2/lists/{list_id}/tweets` | List timeline |
| GET | `/2/lists/{list_id}/members` | Members |
| POST | `/2/lists/{list_id}/members` | Body `{list_id, user_id}` |
| DELETE | `/2/lists/{list_id}/members/{user_id}` | Remove member |
| GET | `/2/lists/{list_id}/followers` | Subscribers |
| GET | `/2/lists/by/owner/{user_id}` | Lists owned by user |
| GET | `/2/users/{user_id}/owned_lists` | Owned lists |
| GET | `/2/users/{user_id}/list_memberships` | Memberships |
| GET | `/2/users/{user_id}/pinned_lists` | Pinned lists |
| POST | `/2/users/{user_id}/pinned_lists` | Body `{list_id}` |
| DELETE | `/2/users/{user_id}/pinned_lists/{list_id}` | Unpin |
| GET | `/2/users/{user_id}/followed_lists` | Followed lists |
| POST | `/2/users/{user_id}/followed_lists` | Body `{list_id}` |
| DELETE | `/2/users/{user_id}/followed_lists/{list_id}` | Unfollow list |
| POST | `/2/lists/{list_id}/pinned` | Pin list |
| DELETE | `/2/lists/{list_id}/pinned` | Unpin list |

## Bookmarks

| Method | Path | Notes |
|---|---|---|
| GET | `/2/users/{user_id}/bookmarks` | Own bookmarks only |
| POST | `/2/users/{user_id}/bookmarks` | Body `{"tweet_id":"..."}` |
| DELETE | `/2/users/{user_id}/bookmarks/{tweet_id}` | Remove bookmark |
| GET | `/2/users/{user_id}/bookmarks/folders` | Folders |
| GET | `/2/users/{user_id}/bookmarks/folders/{folder_id}` | Folder timeline |

## Communities

| Method | Path | Notes |
|---|---|---|
| GET | `/2/communities/{community_id}` | Community detail |
| GET | `/2/communities/search` | 501 stub |

## Spaces

| Method | Path | Notes |
|---|---|---|
| GET | `/2/spaces?ids=a,b` | Bulk Space lookup |
| GET | `/2/spaces/{space_id}` | Space detail (replays + listeners) |
| GET | `/2/spaces/topics` | Browse topics |
| GET | `/2/spaces/{space_id}/buyers` | 501 stub (OAuth2) |
| GET | `/2/spaces/by/creator_ids` | 501 stub |
| GET | `/2/spaces/{space_id}/tweets` | 501 stub |

## Trends

| Method | Path | Notes |
|---|---|---|
| GET | `/2/trends?woeid=1` | Legacy, `woeid` default 1 (worldwide) |
| GET | `/2/trends/by/woeid/{woeid}` | Preferred; 1=worldwide, 23424977=US, 23424775=ID |

## DMs and XChat

| Method | Path | Notes |
|---|---|---|
| POST | `/2/dm_conversations` | Body `{conversation_type, participant_ids, message:{text}}` |
| POST | `/2/dm_conversations/with/{participant_id}/messages` | Body `{text, media_id?, attachments?, reply_to_dm_event_id?}` |
| POST | `/2/dm_conversations/{conversation_id}/messages` | Same body |
| DELETE | `/2/dm_events/{event_id}` | Delete own message |
| POST | `/2/users/{user_id}/dm/block` | Block in DM |
| POST | `/2/users/{user_id}/dm/unblock` | Unblock in DM |
| POST | `/2/chat/conversations/*` | 501 stubs (XChat needs OAuth2) |
| POST | `/2/chat/media/upload/*` | 501 stubs |

## Media

| Method | Path | Notes |
|---|---|---|
| POST | `/2/media/upload?media_type=image/jpeg` | Raw file bytes as request body; optional `media_category` (`tweet_image\|tweet_video\|tweet_gif\|dm_image\|dm_video`, auto-detected) |
| POST | `/2/media/metadata` | JSON `{media_id, alt_text:{text}}` (X media metadata schema) |
| POST | `/2/media/upload/initialize` | 501 stub — use `/2/media/upload` |
| POST | `/2/media/upload/{media_id}/append` | 501 stub |
| POST | `/2/media/upload/{media_id}/finalize` | 501 stub |

## Birdwatch (Community Notes)

| Method | Path | Notes |
|---|---|---|
| POST | `/2/notes` | Body `{tweet_id, data, is_media_note?, is_helpful_for_all_posts?}` |
| POST | `/2/evaluate_note` | Body `{note_id, tweet_id, data, rating_source?, source_platform?, for_live_note?, suggestion?}` |
| DELETE | `/2/notes/{note_id}` | Delete own note |
| GET | `/2/notes/search/notes_written?alias=` | Notes written by contributor |
| GET | `/2/notes/search/posts_eligible_for_notes?tweet_id=` | BatSignal eligible posts |

## Infra

| Method | Path | Notes |
|---|---|---|
| GET | `/info` | Service metadata |
| GET | `/login` | Validate token + profile |
| GET | `/admin/stats` | Requires `X-Admin-Token` (404 if unset) |
| POST | `/search` | Legacy Playwright search, body `{auth_token?, q, type}` |
| GET | `/openapi.json` | Machine-readable route schema |
| GET | `/docs`, `/redoc` | Swagger / ReDoc |
| GET | `/` | Interactive docs UI |

## Stub routes (return 501)

`/2/communities/search`, all `/2/chat/*`, `/2/media/upload/{initialize,append,finalize}`,
`/2/spaces/{id}/buyers`, `/2/spaces/by/creator_ids`, `/2/spaces/{id}/tweets`,
`/2/users/public_keys`, `/2/users/{id}/public_keys` (GET/POST).
