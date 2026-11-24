"""R88 — daftar percakapan XChat dari OPFS SQLite (sweep/inbox bot).

Fase R87 memulihkan bacaan PER percakapan. Tapi `unlock_and_read_xchat_inbox`
(masih DOM-scraper) tetap membayar wait DOM yang tidak pernah menampilkan
baris di headless — sweep percakapan baru bot menunggu 12-25s per panggilan
dan menghabiskan slot semaphore Xapi, menjadikan fetch percakapan menunggu
antrian (33-43s via HTTP walau jalur cepat cuma 8s).

Kontrak (R88):
- `query_inbox_rows(conn, bot_user_id, limit)`: daftar percakapan dari
  dm_entry terbaru per conversation_id (plain_text sebagai preview,
  timestamp sebagai umur) — pola keluaran sama dengan scraper inbox lama:
  {id, conv_href, preview_text, relative_age_ms, is_unread, ...}.
- unlock_and_read_xchat_inbox memakai OPFS dulu (my_user_id ada), fallback
  DOM.
"""
import sqlite3
from datetime import datetime, timezone

import pytest

import app.xchat_e2ee as xee


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE dm_entry (
            entry_id TEXT, conversation_id TEXT, sequence_number INTEGER,
            timestamp INTEGER, entry_type TEXT, contents BLOB,
            sender_id INTEGER, message_status TEXT, plain_text TEXT,
            has_attachment INTEGER, affects_sort_order INTEGER,
            affects_read_state INTEGER, event_type TEXT,
            attachment_types TEXT, deleted INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE dm_conversation (
            conversation_id TEXT, muted INTEGER, deleted INTEGER, trusted INTEGER
        )
    """)
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    rows = [
        # (conv, ts_offset, text, sender)
        ("1394249284736864258:1650073101168959488", 60_000, "wots pesan baru banget", 1650073101168959488),
        ("1394249284736864258:1894189851299516416", 3_600_000, "wots pesan sejam lalu", 1894189851299516416),
        ("1176140322570530816:1394249284736864258", 86_400_000, "wots pesan kemarin", 1176140322570530816),
    ]
    for i, (conv, off, text, sender) in enumerate(rows):
        conn.execute(
            "INSERT INTO dm_entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"e{i}", conv, i, now_ms - off, "message", b"x", sender,
             "Sent", text, 0, 1, 1, None, None, 0),
        )
        conn.execute(
            "INSERT INTO dm_conversation VALUES (?,?,?,?)", (conv, 0, 0, 1)
        )
    return conn


def test_query_inbox_rows_orders_latest_first_with_preview():
    conn = _make_db()
    rows = xee.query_inbox_rows(conn, bot_user_id="1394249284736864258", limit=10)
    assert len(rows) >= 3
    first = rows[0]
    assert first["id"] == "1394249284736864258-1650073101168959488"
    assert "baru" in first["preview_text"]
    assert isinstance(first["relative_age_ms"], int)
    assert first["relative_age_ms"] < 120_000


def test_query_inbox_rows_limits_and_drops_deleted():
    conn = _make_db()
    conn.execute(
        "INSERT INTO dm_entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("dead", "999:888", 9, 1, "message", b"x", 1, "Sent",
         "pesan terhapus", 0, 1, 1, None, None, 1),
    )
    rows = xee.query_inbox_rows(conn, bot_user_id="1394249284736864258", limit=10)
    ids = [r["id"] for r in rows]
    assert "999-888" not in ids


def test_inbox_event_projection_keeps_conv_id_format():
    conn = _make_db()
    rows = xee.query_inbox_rows(conn, bot_user_id="1394249284736864258", limit=10)
    for r in rows:
        assert ":" not in r["id"], "id percakapan wajib format minus (pemisah -)"


def test_query_inbox_rows_not_starved_by_deleted_or_group_or_ties():
    """Percakapan 1:1 aktif tidak boleh terpotong LIMIT bila di atasnya ada banyak
    percakapan terhapus, grup (tanpa ':'), atau tie timestamp yang sama."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE dm_entry (
            entry_id TEXT, conversation_id TEXT, sequence_number INTEGER,
            timestamp INTEGER, entry_type TEXT, contents BLOB,
            sender_id INTEGER, message_status TEXT, plain_text TEXT,
            has_attachment INTEGER, affects_sort_order INTEGER,
            affects_read_state INTEGER, event_type TEXT,
            attachment_types TEXT, deleted INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE dm_conversation (
            conversation_id TEXT, muted INTEGER, deleted INTEGER, trusted INTEGER
        )
    """)
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    # 15 percakapan terhapus di paling atas (timestamp paling baru)
    for i in range(15):
        cid = f"1394249284736864258:{1000 + i}"
        conn.execute(
            "INSERT INTO dm_entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"del-{i}", cid, i, now_ms - i, "message", b"x", 1000 + i, "Sent", "del", 0, 1, 1, None, None, 0),
        )
        conn.execute("INSERT INTO dm_conversation VALUES (?,?,?,?)", (cid, 0, 1, 1))
    # 10 percakapan grup (tanpa ':')
    for i in range(10):
        cid = f"group{i}"
        conn.execute(
            "INSERT INTO dm_entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"grp-{i}", cid, i, now_ms - 100 - i, "message", b"x", 2000 + i, "Sent", "grp", 0, 1, 1, None, None, 0),
        )
        conn.execute("INSERT INTO dm_conversation VALUES (?,?,?,?)", (cid, 0, 0, 1))
    # 5 percakapan 1:1 aktif (termasuk tie timestamp di percakapan pertama)
    for i in range(5):
        cid = f"1394249284736864258:{3000 + i}"
        ts = now_ms - 10_000 - i * 1000
        conn.execute(
            "INSERT INTO dm_entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"act-{i}-a", cid, 1, ts, "message", b"x", 3000 + i, "Sent", f"aktif {i}", 0, 1, 1, None, None, 0),
        )
        conn.execute(
            "INSERT INTO dm_entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"act-{i}-b", cid, 2, ts, "message", b"x", 3000 + i, "Sent", f"aktif {i} tie", 0, 1, 1, None, None, 0),
        )
        conn.execute("INSERT INTO dm_conversation VALUES (?,?,?,?)", (cid, 0, 0, 1))

    rows = xee.query_inbox_rows(conn, bot_user_id="1394249284736864258", limit=5)
    assert len(rows) == 5
    got_ids = [r["id"] for r in rows]
    assert got_ids == [f"1394249284736864258-{3000 + i}" for i in range(5)]


def test_format_dm_events_merges_gql_and_rest_non_destructively():
    """Duplikat id antar-sumber GraphQL/REST harus menggabung field tanpa
    menimpa teks plaintext dengan string kosong atau placeholder E2EE."""
    from formatter import _merge_dm_event_obj, format_dm_events

    plain_ev = {
        "id": "2000000000000000001",
        "event_type": "MessageCreate",
        "dm_conversation_id": "1-2",
        "sender_id": "2",
        "text": "wots ini teks asli",
        "created_at": "2026-11-23T10:00:00.000Z",
    }
    rest_empty_with_entities = {
        "id": "2000000000000000001",
        "event_type": "MessageCreate",
        "dm_conversation_id": "1-2",
        "sender_id": "2",
        "text": "",
        "entities": {"hashtags": [], "mentions": [], "urls": [{"url": "https://t.co/x", "expanded_url": "https://example.com"}]},
    }
    merged = _merge_dm_event_obj(plain_ev, rest_empty_with_entities)
    assert merged["text"] == "wots ini teks asli"
    assert merged["entities"]["urls"][0]["expanded_url"] == "https://example.com"
    assert "_xchat_encrypted" not in merged

    # Urutan terbalik: stub terenkripsi duluan, plaintext menyusul -> plaintext menang
    enc_stub = {
        "id": "2000000000000000002",
        "event_type": "MessageCreate",
        "text": "[XChat E2EE Encrypted Message]",
        "_xchat_encrypted": True,
        "encrypted_text": "cipher==",
    }
    merged2 = _merge_dm_event_obj(enc_stub, plain_ev)
    assert merged2["text"] == "wots ini teks asli"
    assert "_xchat_encrypted" not in merged2
    assert "encrypted_text" not in merged2

    # End-to-end lewat format_dm_events: GraphQL plaintext + REST entities ber-teks kosong
    payload = {
        "data": {
            "get_inbox_page": {
                "messages": [
                    {
                        "id": "2000000000000000003",
                        "conversation_id": "1:2",
                        "sender_id": "2",
                        "text": "wots jangan terhapus",
                        "created_at_ms": "1763892000000",
                    }
                ]
            }
        },
        "inbox_initial_state": {
            "entries": [
                {
                    "message": {
                        "id": "2000000000000000003",
                        "conversation_id": "1-2",
                        "time": "1763892000000",
                        "message_data": {
                            "sender_id": "2",
                            "text": "",
                            "entities": {
                                "urls": [{"url": "https://t.co/a", "expanded_url": "https://example.org"}]
                            },
                        },
                    }
                }
            ]
        },
    }
    formatted = format_dm_events(payload)
    assert len(formatted["data"]) == 1
    ev = formatted["data"][0]
    assert ev["text"] == "wots jangan terhapus"
    assert ev["entities"]["urls"][0]["expanded_url"] == "https://example.org"


@pytest.mark.asyncio
async def test_v2_dm_conversations_opfs_new_convs_not_truncated_by_stale_graphql(monkeypatch):
    """Percakapan E2EE baru dari OPFS/sidebar TIDAK boleh terpotong [:max_results]
    ketika GraphQL mengembalikan max_results percakapan lama."""
    import app.routers.dm as dm_router

    async def fake_graphql_call(*args, **kwargs):
        return {
            "status": "ok",
            "http_status": 200,
            "data": {
                "data": {
                    "get_initial_chat_page": {
                        "conversations": [
                            {
                                "conversation_id": f"100:{200 + i}",
                                "latest_message": {
                                    "id": str(1900000000000000000 + i),
                                    "conversation_id": f"100:{200 + i}",
                                    "sender_id": str(200 + i),
                                    "text": f"lama {i}",
                                    "created_at": f"2026-11-20T0{i}:00:00.000Z",
                                },
                            }
                            for i in range(3)
                        ]
                    }
                }
            },
        }

    async def fake_dm_call(*args, **kwargs):
        return {"status": "error", "http_status": 404, "data": None}

    async def fake_resolve_me_id(tok):
        return "100"

    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

    async def fake_unlock_inbox(tok, pin, my_user_id=None, max_results=50):
        return [
            {
                "id": "100-901",
                "conv_href": "/i/chat/100-901",
                "preview_text": "wots baru banget",
                "relative_age_ms": 5_000,
                "last_ts": now_ms - 5_000,
                "last_sender_id": "901",
            },
            {
                "id": "100-902",
                "conv_href": "/i/chat/100-902",
                "preview_text": "wots baru kedua",
                "relative_age_ms": 30_000,
                "last_ts": now_ms - 30_000,
                "last_sender_id": "902",
            },
        ]

    monkeypatch.setattr(dm_router, "graphql_call", fake_graphql_call)
    monkeypatch.setattr(dm_router, "dm_call", fake_dm_call)
    monkeypatch.setattr(dm_router, "resolve_me_id", fake_resolve_me_id)
    monkeypatch.setattr(dm_router, "unlock_and_read_xchat_inbox", fake_unlock_inbox)
    monkeypatch.setattr(dm_router, "resolve_dm_pin", lambda header, query=None: "1234")

    resp = await dm_router.v2_chat_conversations(
        max_results=3,
        pagination_token=None,
        mode="auto",
        dm_pin=None,
        x_dm_pin="1234",
        authorization="Bearer " + "a" * 40,
        auth_token=None,
        raw=0,
    )
    import json as _json
    body = _json.loads(resp.body)
    ids = [c["id"] for c in body["data"]]
    assert len(ids) == 3
    assert ids[0] == "100-901"
    assert ids[1] == "100-902"


def test_format_dm_conversations_synthesizes_missing_convs_and_matches_reversed_cid():
    """format_dm_conversations tidak boleh menjatuhkan percakapan yang hanya ada
    di events (tanpa map conversations) dan tetap mencocokkan ID terbalik a-b/b-a."""
    from formatter import format_dm_conversations

    payload = {
        "data": {
            "get_inbox_page": {
                "conversations": [
                    {"conversation_id": "200:100"}
                ],
                "messages": [
                    {
                        "id": "2000000000000000101",
                        "conversation_id": "100:200",
                        "sender_id": "200",
                        "text": "wots pasangan terbalik",
                        "created_at_ms": "1763892000000",
                    },
                    {
                        "id": "2000000000000000102",
                        "conversation_id": "100:300",
                        "sender_id": "300",
                        "text": "wots conv tanpa map",
                        "created_at_ms": "1763892060000",
                    },
                ],
            }
        }
    }
    res = format_dm_conversations(payload)
    by_id = {c["id"]: c for c in res["data"]}
    assert "100-300" in by_id
    assert by_id["100-300"]["last_message_event"]["text"] == "wots conv tanpa map"
    assert "200-100" in by_id
    assert by_id["200-100"]["last_message_event"]["text"] == "wots pasangan terbalik"
