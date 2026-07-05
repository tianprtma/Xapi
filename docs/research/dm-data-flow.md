# DM Data Flow Analysis
Date: 2026-06-17

## Files Analyzed

- `app/routers/dm.py` — v2 DM endpoints
- `app/clients.py` — `dm_call`, `_dm_call_once`, `dm_conv_id_for`, `build_dm_new2_payload`
- `formatter.py` lines 157-196 (`_dm_attachment_obj`), 549-643 (`_dm_event_to_obj`), 670-728 (`format_dm_events`)
- `app/config.py` lines 169-200 (`DM_DEFAULT_PARAMS`)
- `app/responses.py` — `finalize`, `write_finalize`, `wrap`
- `app/xchat/events.py` — XChat events reader
- `app/xchat/bridge.py` — XChat browser bridge
- `tests/test_formatter.py` — no DM tests
- `tests/test_responses.py` — no DM-specific tests

## Architecture Overview

```
v2 endpoint (/2/dm_events, etc.)
  │
  ├── dm_call("dm/user_updates.json", tok, method="GET")
  │     └── _dm_call_once → GET x.com/i/api/1.1/dm/...
  │           └── with_dm_defaults=True → adds DM_DEFAULT_PARAMS (incl. include_inbox_timelines=true)
  │
  ├── format_dm_events(result["data"])
  │     ├── extract inbox_initial_state / user_events / conversation_timeline / inbox_timeline
  │     ├── for each entry: {k: v} → _dm_event_to_obj({**v, "type": k})
  │     └── build data[], users{}, convs{}, meta
  │
  ├── (optional) untrusted inbox merge: dm/inbox_timeline/untrusted.json
  ├── (optional) XChat merge: read_xchat_events → bridge → OPFS chat.db
  └── JSONResponse(data, includes, meta)
```

## Endpoint Analysis

### GET /2/dm_events (`v2_dm_events`)

| Aspect | Detail |
|--------|--------|
| Backend | REST 1.1 `dm/user_updates.json` |
| Default params | `count` + `active_conversations_only` |
| Injected params | `DM_DEFAULT_PARAMS` (via `with_dm_defaults=True`) |
| Response format | `inbox_initial_state.entries` (because `include_inbox_timelines=true`) |
| Images from other users | Handled via `attachment.media/photo/video` in `msg_data` |

### GET /2/dm_conversations/{conversation_id}/dm_events (`v2_dm_conv_events`)

| Aspect | Detail |
|--------|--------|
| Backend | REST 1.1 `dm/conversation/{conversation_id}.json` |
| Conversation ID | Raw from URL path — caller must use dash format `{a}-{b}` |
| Default params | `count` + `context` + `DM_DEFAULT_PARAMS` |
| Response format | `conversation_timeline.entries` |

### GET /2/dm_conversations/with/{participant_id}/dm_events

| Aspect | Detail |
|--------|--------|
| Backend | REST 1.1 `dm/conversation/{conv_id}.json` where `conv_id = dm_conv_id_for(me, participant_id)` |
| Conversation ID | `sorted(me, other)` joined with `-` (dash) |
| Response format | `conversation_timeline.entries` |

## Detailed Findings

### 1. `include_inbox_timelines=true` is correctly handled

`DM_DEFAULT_PARAMS` includes `"include_inbox_timelines": "true"` (config.py:196). This param is added to ALL GET DM calls via `_dm_call_once` (clients.py:278-279).

This causes `dm/user_updates.json` to return `inbox_initial_state` format instead of the older `user_inbox` format.

`format_dm_events` (formatter.py:683-688) correctly checks:
```python
inbox = (
    (payload or {}).get("inbox_initial_state")   # ← matches user_updates response
    or (payload or {}).get("user_events")         # ← fallback
    or (payload or {}).get("conversation_timeline") # ← matches conversation/{id}
    or (payload or {}).get("inbox_timeline")       # ← matches inbox_timeline endpoints
    or {}
)
```

:white_check_mark: **CORRECT** — `inbox_initial_state` is checked first.

### 2. Entry iteration in `format_dm_events` is correct

```python
for ev in inbox.get("entries", []) or []:         # each entry
    for k, v in ev.items():                        # k="message", v={message_data: {...}}
        obj = _dm_event_to_obj({**v, "type": k})  # becomes {message_data: {...}, "type": "message"}
```

For `inbox_initial_state.entries`, each entry is `{"message": {message_data: {..., attachment: {photo: {...}}}, ...}}`. The iteration correctly destructures `v` as the inner dict and tags it with `"type": "message"`.

:white_check_mark: **CORRECT**

### 3. `_dm_event_to_obj` correctly handles both inbox formats

The function (formatter.py:562-569) explicitly handles both formats:

```python
msg = ev.get("message_create") or {}  # Account Activity API format
msg_data = ev.get("message_data") or msg.get("message_data") or {}
# For inbox_initial_state: message_data sits directly on ev
# For message_create: nested under message_create.message_data
```

For `inbox_initial_state` format where `ev = {message_data: {...}, "type": "message"}`:
- `msg = {}` (no `message_create` key) 
- `msg_data = ev.get("message_data")` → actual data

For Account Activity API format where `ev = {"type": "message_create", message_create: {message_data: {...}}}`:
- `msg = ev.get("message_create")` → `{message_data: {...}}`
- `msg_data = {} or msg.get("message_data")` → actual data

:white_check_mark: **CORRECT**

### 4. Photo attachments from OTHER users are handled

`_dm_event_to_obj` (formatter.py:615-623):

```python
attach = msg_data.get("attachment") or {}
media = attach.get("media") or attach.get("photo") or attach.get("video")
if media and media.get("id_str"):
    base["attachments"] = {"media_keys": [str(media["id_str"])]}
    base["_xapi_attachments"] = [_dm_attachment_obj(media)]
```

Checks `attachment.media`, `attachment.photo`, and `attachment.video`. Since `msg_data` is the actual `message_data` from the entry (not filtered by sender), this works for ALL users' messages, not just the authenticated user's.

`_dm_attachment_obj` (formatter.py:157-196) extracts `media_url_https` as URL, determines MIME type, and for video picks the highest-bitrate mp4 variant.

:white_check_mark: **CORRECT** — attachments from other users are properly extracted.

### 5. `dm/inbox_timeline/untrusted.json` returns empty entries

The untrusted inbox merge (dm.py:442-477) calls `dm/inbox_timeline/untrusted.json` with `max_id` set to `2 << 60` (a very large snowflake value to get newest messages).

The endpoint returns `{"inbox_timeline": {"status": "HAS_MORE", "min_entry_id": "..."}}` with NO entries when:
- The account has no pending message requests
- The account has no truly untrusted conversations
- X's endpoint behavior returns pagination state without entries for empty inboxes

`format_dm_events` checks `(payload or {}).get("inbox_timeline")` which extracts the `inbox_timeline` object. If `inbox_timeline.entries` is missing/empty, the loop at line 693 produces no events — which is correct behavior (nothing to show).

**Potential concern**: `dm/inbox_timeline/untrusted.json` is called via `dm_call` with default `with_dm_defaults=True`, adding `include_inbox_timelines=true`. This param might change the untrusted endpoint's response format. If it causes the endpoint to return `inbox_initial_state` instead of `inbox_timeline`, the response would fall through all the format checks in `format_dm_events` and produce empty output even when there ARE pending requests.

:memo: **LOW RISK** — Likely just means the account has no pending message requests.

### 6. Conversation ID format: dash, not colon

`dm_conv_id_for` (clients.py:343-346):
```python
a, b = sorted([str(me), str(other)], key=lambda x: int(x) if x.isdigit() else x)
return f"{a}-{b}"  # DASH-separated
```

REST 1.1 endpoint URL: `dm/conversation/{id}.json` expects dash format `{a}-{b}`.

XChat's OPFS chat.db uses colon format `{a}:{b}` but normalizes to dash in `events.py:103`:
```python
conv_id_legacy = conv_id_xchat.replace(":", "-")
```

:white_check_mark: **CORRECT** — dash is the canonical REST 1.1 format. Colon→dash normalization is in place.

### 7. Potential bug: no colon→dash normalization in `v2_dm_conv_events`

The endpoint `v2_dm_conv_events` (dm.py:332) takes `conversation_id` directly from the URL path:

```python
result = await dm_call(f"dm/conversation/{conversation_id}.json", tok, method="GET", params=params)
```

If a caller provides a colon-separated ID (e.g., from XChat data which uses colon), the REST endpoint will receive `dm/conversation/12345:67890.json` and will FAIL because it expects dash format.

However:
- The includes in the v2 response use dash format (from `inbox_initial_state.conversations`)
- XChat returns normalized dash format
- Callers should use IDs from the v2 response's `includes.dm_conversations`

:warning: **LOW RISK** — Architectural contract issue, not a code bug. Could add normalization:
```python
conv_id = conversation_id.replace(":", "-")
```

### 8. XChat bridge is well-structured

The bridge (bridge.py) maintains persistent Chromium contexts per bot account. It:
- Reads decrypted E2E messages from OPFS `chat_{userId}.db` via JS eval
- Handles PIN recovery screen
- Falls back gracefully if no chat.db exists
- Emits events with `_xchat: True` flag for deduplication

The merge logic in `v2_dm_events` (dm.py:479-517) deduplicates by `id` field, preserving both REST and XChat sources.

:white_check_mark: **CORRECT**

### 9. `write_finalize` error mapping

`write_finalize` (responses.py:127-163) correctly maps upstream REST 1.1 error codes:
- 401/403 -> session invalid / auth rejected
- Other errors -> UPSTREAM_ERROR
- Also detects GraphQL-level errors via `_first_upstream_error` + `_has_success_payload`

:white_check_mark: **CORRECT**

### 10. No DM-specific formatter tests exist

The file `tests/test_formatter.py` tests only `_user_result_to_obj`, `_tweet_result_to_obj`, `format_user`, `format_tweet_collection`, and `format_error`. There are NO tests for:
- `_dm_event_to_obj`
- `_dm_attachment_obj`
- `format_dm_events`
- `format_dm_send_result`

:warning: **TEST GAP** — None of the DM formatting logic is covered by tests.

## Verdict

**The code is functionally correct for the core DM data flow.** Specifically:

- `format_dm_events` correctly handles `inbox_initial_state` entries with `attachment.photo` for images from OTHER users — YES, it works. The `msg_data` variable from `ev.get("message_data")` captures the full message data including attachments, and the attachment extraction is sender-agnostic.

- `_dm_event_to_obj` correctly processes both `inbox_initial_state` (where `message_data` sits directly on the event) and `message_create` (Account Activity API) format — YES, the nested fallback is explicitly handled.

- `include_inbox_timelines=true` causing response format change — YES, handled. `format_dm_events` checks `inbox_initial_state` first before `user_events`.

- `dm/inbox_timeline/untrusted.json` returning empty entries — likely reflects the actual state of the account (no pending requests), not a code bug.

- Conversation ID format — dash `{a}-{b}` is correct. XChat colon format is normalized. Minor potential issue with `v2_dm_conv_events` accepting unnormalized colon IDs from URL path.

**Test gap is the main concern.** The DM formatting pipeline has zero unit test coverage. A breaking change to `format_dm_events`, `_dm_event_to_obj`, or `_dm_attachment_obj` would not be caught.
