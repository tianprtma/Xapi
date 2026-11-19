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
