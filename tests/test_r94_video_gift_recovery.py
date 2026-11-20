"""R94 — recovery media video/GIF dari OPFS aman & benar jenisnya.

Pertanyaan pemilik: "media video gift aman kan?". Jalur R90 membaca file
terdekripsi dm_local_attachment. Video/GIF harus diklasifikasikan benar
(bukan cuma dari ekstensi) agar worker memprosesnya sebagai tweet_video /
tweet_gif, bukan foto. Gift bukan file media (event_type berbeda) sehingga
tidak diposting sebagai media — aman.

Kontrak (R94):
- attachment_type MediaVideo / file .mp4/.mov → attachment kind video,
  mime video/mp4 atau video/quicktime.
- attachment_type MediaAnimatedGif / file .gif → mime image/gif (worker
  memetakannya ke tweet_gif).
- byte_size selalu disertakan agar worker menegakkan batas ukuran.
"""
import sqlite3
from unittest.mock import AsyncMock

import pytest

import app.xchat_e2ee as xee

MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64


def _conn(message_id, path, attachment_type):
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE dm_local_attachment (
            attachment_id TEXT, file_number INTEGER, local_path TEXT,
            downloaded_at INTEGER, file_size INTEGER, conversation_id TEXT,
            message_id TEXT, attachment_type TEXT, mime_type TEXT, metadata TEXT
        )
    """)
    conn.execute("INSERT INTO dm_local_attachment VALUES (?,?,?,?,?,?,?,?,?,?)",
                 ("a1", 1, path, 1, len(MP4), "1:2", message_id, attachment_type, None, None))
    return conn


def _pending(eid="vid1"):
    rows = [{"entry_id": eid, "timestamp": 1795103224636, "sender_id": 1,
             "plain_text": "/send video menfess", "has_attachment": 1,
             "message_status": "Sent", "deleted": 0, "attachment_types": "media",
             "contents": b"attachmentId\x00x"}]
    events = xee.project_dm_entries_to_events(rows, "1-2")
    return rows, events


@pytest.mark.asyncio
async def test_video_recovery_kind_and_mime(monkeypatch):
    rows, events = _pending()
    conn = _conn("vid1", "dm-files-1/decrypted-media-v2/1-2/vid1/clip.mp4", "MediaVideo")
    monkeypatch.setattr(xee, "read_xchat_opfs_file", AsyncMock(return_value=MP4))

    await xee.recover_opfs_media_for_events(conn, None, None, rows, events)

    att = events[0]["_xapi_attachments"][0]
    assert att["kind"] == "video"
    assert att["mime"] == "video/mp4"
    assert att["byte_size"] == len(MP4)
    assert events[0]["_xchat_media_state"] == "ready"


@pytest.mark.asyncio
async def test_gif_recovery_mime(monkeypatch):
    rows, events = _pending("gif1")
    conn = _conn("gif1", "dm-files-1/decrypted-media-v2/1-2/gif1/anim.gif", "MediaAnimatedGif")
    monkeypatch.setattr(xee, "read_xchat_opfs_file", AsyncMock(return_value=GIF))

    await xee.recover_opfs_media_for_events(conn, None, None, rows, events)

    att = events[0]["_xapi_attachments"][0]
    assert att["mime"] == "image/gif"
    assert att["byte_size"] == len(GIF)


@pytest.mark.asyncio
async def test_video_classification_from_attachment_type_without_ext(monkeypatch):
    """File tanpa ekstensi jelas tetap video bila attachment_type MediaVideo."""
    rows, events = _pending("vid2")
    conn = _conn("vid2", "dm-files-1/decrypted-media-v2/1-2/vid2/blob", "MediaVideo")
    monkeypatch.setattr(xee, "read_xchat_opfs_file", AsyncMock(return_value=MP4))

    await xee.recover_opfs_media_for_events(conn, None, None, rows, events)

    att = events[0]["_xapi_attachments"][0]
    assert att["kind"] == "video"
    assert att["mime"].startswith("video/")