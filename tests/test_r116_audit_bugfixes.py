"""Regression tests for Round 19 algorithmic bugfixes in Xapi."""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from app.routers.dm import _enrich_conv_events_with_e2ee, _format_dm_conversations_smart
from app.security import BodySizeLimitMiddleware
from app.xchat_e2ee import query_dm_entries, query_inbox_rows
from formatter import _dm_ts_to_iso, format_dm_events


@pytest.mark.asyncio
async def test_enrich_conv_events_appends_newest_first_extras():
    """When OPFS returns chronological (oldest-first) decrypted events and max_results
    truncates extras, _enrich_conv_events_with_e2ee must keep the NEWEST extras."""
    formatted = {
        "data": [
            {
                "id": "9999999999999999999",
                "event_type": "MessageCreate",
                "dm_conversation_id": "100-200",
                "sender_id": "200",
                "text": "[XChat E2EE Encrypted Message]",
                "_xchat_encrypted": True,
                "created_at": "2026-11-24T10:05:00.000Z",
            }
        ],
        "meta": {"result_count": 1},
    }
    # Chronological oldest-first list (as returned by project_dm_entries_to_events)
    opfs_chrono = [
        {
            "id": "u-oldest",
            "event_type": "MessageCreate",
            "dm_conversation_id": "100-200",
            "sender_id": "200",
            "text": "old 1",
            "created_at": "2026-11-24T08:00:00.000Z",
            "_xchat_media_state": "none",
        },
        {
            "id": "u-mid",
            "event_type": "MessageCreate",
            "dm_conversation_id": "100-200",
            "sender_id": "200",
            "text": "mid 2",
            "created_at": "2026-11-24T09:00:00.000Z",
            "_xchat_media_state": "none",
        },
        {
            "id": "u-recent",
            "event_type": "MessageCreate",
            "dm_conversation_id": "100-200",
            "sender_id": "200",
            "text": "recent 3",
            "created_at": "2026-11-24T10:00:00.000Z",
            "_xchat_media_state": "none",
        },
        {
            "id": "u-latest",
            "event_type": "MessageCreate",
            "dm_conversation_id": "100-200",
            "sender_id": "200",
            "text": "latest 4",
            "created_at": "2026-11-24T10:05:00.000Z",
            "_xchat_media_state": "none",
        },
    ]
    with (
        patch("app.routers.dm.resolve_me_id", new=AsyncMock(return_value="100")),
        patch("app.routers.dm.unlock_and_read_xchat_conversation", new=AsyncMock(return_value=opfs_chrono)),
    ):
        res = await _enrich_conv_events_with_e2ee(
            formatted, tok="a" * 40, pin="123456", conv_id="100-200", max_results=2
        )
    texts = [ev["text"] for ev in res["data"]]
    assert texts == ["latest 4", "recent 3"]


def test_query_dm_entries_matches_swapped_conv_id_and_inbox_dedupes():
    """query_dm_entries must find rows regardless of a:b vs b:a order, and
    query_inbox_rows must deduplicate swapped 1:1 IDs."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE dm_entry (
            entry_id TEXT, conversation_id TEXT, timestamp INTEGER,
            sender_id INTEGER, plain_text TEXT, has_attachment INTEGER,
            message_status TEXT, deleted INTEGER, event_type TEXT,
            attachment_types TEXT, contents BLOB
        )
        """
    )
    conn.execute(
        "INSERT INTO dm_entry VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("e1", "100:200", 1700000001000, 200, "first msg", 0, "Sent", 0, None, None, b""),
    )
    conn.execute(
        "INSERT INTO dm_entry VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("e2", "200:100", 1700000002000, 200, "second msg", 0, "Sent", 0, None, None, b""),
    )
    rows = query_dm_entries(conn, "200:100", limit=10)
    assert [r["entry_id"] for r in rows] == ["e2", "e1"]

    inbox = query_inbox_rows(conn, "100", limit=10)
    assert len(inbox) == 1
    assert inbox[0]["preview_text"] == "second msg"
    conn.close()


def test_dm_ts_to_iso_no_float_rounding_jump():
    """999999us must stay at .999Z on the same second, never wrap to .000Z."""
    assert _dm_ts_to_iso("2026-11-24T10:00:00.999999Z") == "2026-11-24T10:00:00.999Z"
    assert _dm_ts_to_iso("2026-11-24T10:00:00.290Z") == "2026-11-24T10:00:00.290Z"
    assert _dm_ts_to_iso("2026-11-24T10:00:00Z") == "2026-11-24T10:00:00.000Z"


def test_format_dm_events_and_conversations_canonicalize_swapped_1to1_ids():
    """GraphQL conv 999:111 + REST conv 111-999 (trusted=False) must merge cleanly
    and propagate trusted=False to GraphQL events."""
    payload = {
        "data": {
            "get_initial_chat_page": {
                "conversations": [
                    {
                        "conversation_id": "999:111",
                        "type": "ONE_TO_ONE",
                        "messages": [
                            {
                                "id": "5001",
                                "sender_id": "999",
                                "text": "halo request",
                                "created_at": "1700000000000",
                            }
                        ],
                    }
                ]
            }
        },
        "inbox_initial_state": {
            "conversations": {
                "111-999": {
                    "conversation_id": "111-999",
                    "type": "ONE_TO_ONE",
                    "trusted": False,
                    "participants": [{"user_id": "111"}, {"user_id": "999"}],
                }
            }
        },
    }
    ev_out = format_dm_events(payload)
    assert len(ev_out["data"]) == 1
    assert ev_out["data"][0]["trusted"] is False
    assert len(ev_out["includes"]["conversations"]) == 1

    conv_out = _format_dm_conversations_smart(payload)
    assert len(conv_out["data"]) == 1
    assert conv_out["data"][0]["trusted"] is False
    assert conv_out["data"][0]["last_message_event"]["id"] == "5001"


def test_body_size_limit_middleware_chunked_no_double_send():
    """Oversized chunked POST must emit exactly one 413 response (start + final body)
    and never forward downstream's response body after more_body=False."""
    sent_messages: list[dict] = []

    async def downstream(scope, receive, send):
        chunks = []
        while True:
            msg = await receive()
            chunks.append(msg.get("body", b""))
            if not msg.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"downstream-ok", "more_body": False})

    mw = BodySizeLimitMiddleware(downstream, max_bytes=10)
    incoming = iter(
        [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"78901234", "more_body": True},
            {"type": "http.request", "body": b"never-read", "more_body": False},
        ]
    )

    async def fake_receive():
        return next(incoming)

    async def fake_send(msg):
        sent_messages.append(msg)

    scope = {"type": "http", "method": "POST", "path": "/2/tweets", "headers": []}
    asyncio.run(mw(scope, fake_receive, fake_send))

    starts = [m for m in sent_messages if m["type"] == "http.response.start"]
    bodies = [m for m in sent_messages if m["type"] == "http.response.body"]
    assert len(starts) == 1
    assert starts[0]["status"] == 413
    assert len(bodies) == 1
    assert bodies[0]["more_body"] is False
    assert b"downstream-ok" not in bodies[0]["body"]
