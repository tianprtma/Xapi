"""R90 — recovery media foto dari OPFS (jalur R87 sebelumnya teks-saja).

KASUS NYATA (19 Nov, conv 2049814363742072832): menfess "/send guys ada yang
tau ga source dua foto ini?" terposting TEXT-ONLY (tweet 2123458283742888292)
— dua foto hilang. Jalur OPFS R87 hanya membaca plain_text; has_attachment
ditandai `_xchat_media_pending` tanpa ekstrak media, lalu R80 timeout 45 menit
memposting teks saja.

Fakta OPFS (diukur via diagnostik): tabel `dm_local_attachment` memetakan
`message_id` (= entry_id) → `local_path` file JPEG SUDAH TERDEKRIPSI di OPFS
(`dm-files-<viewer>/decrypted-media-v2/<conv>/<entry>/<hash>.jpg`); bytes
terbaca via navigator.storage.getDirectory (magic ffd8ffe0). Jumlah lampiran
terhitung dari `attachmentId` dalam contents BLOB dm_entry.

Kontrak (R90):
- `recover_opfs_media_for_events(conn, page, context, rows, events)`: untuk
  event pending, baca file dm_local_attachment dari OPFS, cache sebagai
  attachment proxy; set `_xapi_attachments` + state ready HANYA bila semua
  lampiran yang diharapkan terpulihkan (bila belum, tetap pending → R80 fallback).
"""
import sqlite3
from unittest.mock import AsyncMock

import pytest

import app.xchat_e2ee as xee


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 512


def _conn_with_local(message_id, paths):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE dm_local_attachment (
            attachment_id TEXT, file_number INTEGER, local_path TEXT,
            downloaded_at INTEGER, file_size INTEGER, conversation_id TEXT,
            message_id TEXT, attachment_type TEXT, mime_type TEXT, metadata TEXT
        )
    """)
    for i, p in enumerate(paths):
        conn.execute(
            "INSERT INTO dm_local_attachment VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"att{i}", 1, p, 1, len(JPEG), "1:2", message_id, "MediaImage", None, None),
        )
    return conn


def _pending_event(eid="cc57d878"):
    rows = [{
        "entry_id": eid, "timestamp": 1795103224636, "sender_id": 2049814363742072832,
        "plain_text": "/send source dua foto ini", "has_attachment": 1,
        "message_status": "Sent", "deleted": 0, "event_type": None,
        "attachment_types": "media",
        "contents": b"attachmentId\x00aaa attachmentId\x00bbb",  # 2 lampiran
    }]
    events = xee.project_dm_entries_to_events(rows, "1-2")
    return rows, events


@pytest.mark.asyncio
async def test_recovers_all_photos_to_ready(monkeypatch):
    rows, events = _pending_event()
    assert events[0]["_xchat_media_pending"] is True
    conn = _conn_with_local("cc57d878", [
        "dm-files-1/decrypted-media-v2/1-2/cc57d878/a.jpg",
        "dm-files-1/decrypted-media-v2/1-2/cc57d878/b.jpg",
    ])
    monkeypatch.setattr(xee, "read_xchat_opfs_file", AsyncMock(return_value=JPEG))

    await xee.recover_opfs_media_for_events(conn, None, None, rows, events)

    ev = events[0]
    assert len(ev.get("_xapi_attachments") or []) == 2
    assert ev["_xchat_media_state"] == "ready"
    assert "_xchat_media_pending" not in ev
    assert ev["attachments"]["media_keys"]


@pytest.mark.asyncio
async def test_partial_recovery_stays_pending(monkeypatch):
    rows, events = _pending_event()  # expected 2
    conn = _conn_with_local("cc57d878", [
        "dm-files-1/decrypted-media-v2/1-2/cc57d878/a.jpg",
    ])  # baru 1 terunduh
    monkeypatch.setattr(xee, "read_xchat_opfs_file", AsyncMock(return_value=JPEG))

    await xee.recover_opfs_media_for_events(conn, None, None, rows, events)

    ev = events[0]
    assert ev.get("_xchat_media_pending") is True, "belum semua foto → tetap pending"
    assert not ev.get("_xapi_attachments")


@pytest.mark.asyncio
async def test_no_local_attachment_stays_pending(monkeypatch):
    rows, events = _pending_event()
    conn = _conn_with_local("other", [])  # tidak ada baris utk entry ini
    monkeypatch.setattr(xee, "read_xchat_opfs_file", AsyncMock(return_value=JPEG))

    await xee.recover_opfs_media_for_events(conn, None, None, rows, events)

    assert events[0].get("_xchat_media_pending") is True


@pytest.mark.asyncio
async def test_non_attachment_event_untouched(monkeypatch):
    rows = [{
        "entry_id": "txt1", "timestamp": 1795103224636, "sender_id": 1,
        "plain_text": "/send halo tanpa foto", "has_attachment": 0,
        "message_status": "Sent", "deleted": 0,
    }]
    events = xee.project_dm_entries_to_events(rows, "1-2")
    conn = _conn_with_local("txt1", [])
    reader = AsyncMock(return_value=JPEG)
    monkeypatch.setattr(xee, "read_xchat_opfs_file", reader)

    await xee.recover_opfs_media_for_events(conn, None, None, rows, events)

    assert "_xapi_attachments" not in events[0]
    reader.assert_not_awaited()