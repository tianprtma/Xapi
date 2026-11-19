"""R87 — XChat OPFS SQLite: pembacaan pesan tanpa menunggu render DOM.

KASUS NYATA (19 Nov): X mengganti XChat ke aplikasi baru (Vite + Module
Federation) yang menyimpan pesan di SQLite OPFS —
`backups/chat_<viewer_id>.db` (18.6 MB, 2187 percakapan, 8618 dm_entry),
disinkronkan lewat websocket chat. Tabel `dm_entry` berisi
`plain_text` SUDAH TERDEKRIPSI + `entry_id` UUID + `timestamp` epoch-ms +
`sender_id`. Render DOM-nya sendiri (baris pesan) tidak pernah muncul di
headless — menunggu baris DOM = hang 60-90s per percakapan.

Ekstraksi db 12.7 detik untuk SEMUA percakapan (vs 30-45s PER percakapan
lewat DOM) — 200x lebih cepat total.

Kontrak (R87):
- `extract_xchat_opfs_db(page)`: baca file OPFS backups/chat_*.db dari
  halaman X via evaluate, kembalikan bytes.
- `project_dm_entries_to_events(rows, conv_id)`: baris dm_entry → event
  format Xapi (id=entry_id, created_at ISO dari timestamp ms, text
  plain_text, sender_id, dm_conversation_id format minus).
- unlock_and_read_xchat_conversation memakai jalur ini SEBAGAI UTAMA
  (fallback DOM lama tetap ada).
"""
import base64
import sqlite3
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.xchat_e2ee as xee


def test_project_dm_entries_maps_row_to_event():
    rows = [
        {
            "entry_id": "55ba31dc-040d-4b8e-9c1d-2e3f4a5b6c7d",
            "timestamp": 1795100248000,
            "sender_id": 1650073101168959488,
            "plain_text": "/send menfess dari sqlite opfs",
            "has_attachment": 0,
            "message_status": "Sent",
            "deleted": 0,
            "event_type": None,
            "attachment_types": None,
        },
    ]
    events = xee.project_dm_entries_to_events(rows, "1394249284736864258-1650073101168959488")
    assert len(events) == 1
    ev = events[0]
    assert ev["id"] == "55ba31dc-040d-4b8e-9c1d-2e3f4a5b6c7d"
    assert ev["dm_conversation_id"] == "1394249284736864258-1650073101168959488"
    assert ev["sender_id"] == "1650073101168959488"
    assert ev["text"] == "/send menfess dari sqlite opfs"
    dt = datetime.fromisoformat(ev["created_at"].replace("Z", "+00:00"))
    assert dt == datetime(2026, 11, 19, 14, 30, 48, tzinfo=timezone.utc).replace(
        year=dt.year
    ) or abs((dt - datetime.fromtimestamp(1795100248000 / 1000, tz=timezone.utc)).total_seconds()) < 1


def test_project_dm_entries_skips_deleted_and_empty():
    rows = [
        {"entry_id": "a", "timestamp": 1, "sender_id": 1, "plain_text": None,
         "has_attachment": 0, "message_status": "Sent", "deleted": 0},
        {"entry_id": "b", "timestamp": 2, "sender_id": 1, "plain_text": "hapus",
         "has_attachment": 0, "message_status": "Sent", "deleted": 1},
    ]
    events = xee.project_dm_entries_to_events(rows, "1-2")
    assert events == []


@pytest.mark.asyncio
async def test_extract_opfs_returns_bytes(monkeypatch):
    db_bytes = b"SQLite format 3\x00" + b"\x00" * 100
    page = MagicMock()
    page.evaluate = AsyncMock(
        return_value=base64.b64encode(db_bytes).decode("ascii")
    )
    data = await xee.extract_xchat_opfs_db(page, viewer_id="1394249284736864258")
    assert data == db_bytes
    args = page.evaluate.await_args.args
    js = args[0]
    file_arg = args[1] if len(args) > 1 else None
    assert file_arg == "chat_1394249284736864258.db"
    assert "backups" in js


@pytest.mark.asyncio
async def test_extract_opfs_handles_missing_file(monkeypatch):
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=None)
    data = await xee.extract_xchat_opfs_db(page, viewer_id="1")
    assert data is None


def test_sqlite_roundtrip_with_projector():
    """Buat sqlite in-memory meniru skema dm_entry → ekstrak via helper
    query → project → event. Menjamin query helper SQL valid."""
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
    conn.execute(
        "INSERT INTO dm_entry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("e1", "1394249284736864258:1650073101168959488", 1, 1795100248000,
         "message", b"x", 1650073101168959488, "Sent",
         "wots isi menfess", 0, 1, 1, None, None, 0),
    )
    rows = xee.query_dm_entries(conn, "1394249284736864258:1650073101168959488", limit=30)
    events = xee.project_dm_entries_to_events(rows, "1394249284736864258-1650073101168959488")
    assert len(events) == 1
    assert events[0]["text"] == "wots isi menfess"
    assert events[0]["_xchat_decrypted"] is True
    assert events[0]["_xchat_media_state"] == "none"
