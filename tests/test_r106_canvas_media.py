"""R106 — gambar E2EE dipanen dari DOM chat yang sudah terdekripsi.

Kasus nyata (conv 1776226317719257088 "cerim bondol"): gambar E2EE tidak
pernah terunduh ke OPFS (unduhan dipicu komponen chat, browser headless
gagal me-render). Tapi client X TETAP mendekripsi & me-render gambar sebagai
`<img src="blob:...">` di shadow DOM — canvas bisa memanen bytes-nya tanpa
RE kripto.

Kontrak (R106):
- `_media_text_hint`: hint pencocokan gambar↔menfess — lowercase, buang token
  trigger (/send, wots) di depan/belakang, ambil maks 5 kata pertama.
- Hint kosong bila teks hanya trigger.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers.dm import _enrich_conv_events_with_e2ee
from app.xchat_e2ee import (
    _EXTRACT_MEDIA_JS,
    _build_rendered_media_specs,
    _extract_rendered_media,
    _media_text_hint,
    project_dm_entries_to_events,
)


def test_hint_strips_trigger_words():
    assert _media_text_hint("cerim bondol+ponian, kabarin kalo biru wots") == \
        "cerim bondol+ponian, kabarin kalo biru"


def test_hint_handles_send_prefix():
    assert _media_text_hint("/send halo dunia menfess") == "halo dunia menfess"


def test_hint_case_insensitive():
    assert _media_text_hint("Cerim Bondol+Ponian WOTS") == "cerim bondol+ponian"


def test_hint_only_trigger_returns_empty():
    assert _media_text_hint("wots") == ""
    assert _media_text_hint("/send wots") == ""
    assert _media_text_hint("") == ""


def test_hint_caps_at_five_words():
    assert _media_text_hint("satu dua tiga empat lima enam tujuh") == \
        "satu dua tiga empat lima"


def test_build_rendered_media_specs_ranks_repeated_caption_from_newest():
    all_events = [
        {
            "id": "ev-old-jun",
            "text": "yg punya fto ini bagi dong wots",
            "created_at": "2026-06-30T13:49:44.148Z",
            "_xchat_media_state": "ready",
            "_xapi_attachments": [{"media_id": "old"}],
        },
        {
            "id": "ev-mid-nov10",
            "text": "yg punya fto ini bagi dong wots",
            "created_at": "2026-11-10T18:27:02.630Z",
            "_xchat_media_pending": True,
            "_xchat_media_state": "pending",
        },
        {
            "id": "ev-new-nov23",
            "text": "yg punya fto ini bagi dong wots",
            "created_at": "2026-11-23T20:15:19.410Z",
            "_xchat_media_pending": True,
            "_xchat_media_state": "pending",
        },
    ]
    pending = [all_events[1], all_events[2]]
    specs = _build_rendered_media_specs(pending, all_events=all_events)
    assert specs[0]["rank_from_newest"] == 1
    assert specs[1]["rank_from_newest"] == 0
    assert specs[1]["ts_ms"] > specs[0]["ts_ms"]
    assert "data-dm-message-row" in _EXTRACT_MEDIA_JS
    assert "allMatching.length - 1 - rankFromNewest" in _EXTRACT_MEDIA_JS


@pytest.mark.asyncio
async def test_extract_rendered_media_records_dimensions_and_passes_specs():
    ev_old = {
        "id": "ev-old",
        "text": "yg punya fto ini bagi dong wots",
        "created_at": "2026-11-10T18:27:02.630Z",
        "_xchat_media_state": "ready",
        "_xapi_attachments": [{"media_id": "old"}],
    }
    ev_new = {
        "id": "ev-new",
        "text": "yg punya fto ini bagi dong wots",
        "created_at": "2026-11-23T20:15:19.410Z",
        "_xchat_media_pending": True,
        "_xchat_media_state": "pending",
    }
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=[
        {"dataUrl": "data:image/jpeg;base64,/9j/2Q==", "width": 627, "height": 726}
    ])
    n = await _extract_rendered_media(page, [ev_new], all_events=[ev_old, ev_new])
    assert n == 1
    assert ev_new["_xchat_media_state"] == "ready"
    assert "_xchat_media_pending" not in ev_new
    assert ev_new["_xapi_attachments"][0]["width"] == 627
    assert ev_new["_xapi_attachments"][0]["height"] == 726
    passed_specs = page.evaluate.await_args.args[1]
    assert passed_specs[0]["rank_from_newest"] == 0


def test_project_dm_entries_sets_is_outgoing_when_my_user_id_provided():
    rows = [
        {"entry_id": "b1", "timestamp": 1795100249000, "sender_id": 1394249284736864258,
         "plain_text": "balasan bot", "has_attachment": 0, "deleted": 0},
        {"entry_id": "u1", "timestamp": 1795100248000, "sender_id": 1751910669786689536,
         "plain_text": "yg punya fto ini bagi dong wots", "has_attachment": 0, "deleted": 0},
    ]
    events = project_dm_entries_to_events(
        rows, "1394249284736864258-1751910669786689536", my_user_id="1394249284736864258"
    )
    by_id = {e["id"]: e for e in events}
    assert by_id["b1"]["is_outgoing"] is True
    assert by_id["u1"]["is_outgoing"] is False


@pytest.mark.asyncio
async def test_enrich_conv_events_sorts_opfs_newest_first_and_blocks_stale_positional_pair():
    # OPFS mengembalikan kronologis (terlama di index 0); GraphQL terbaru di index 0.
    # Placeholder baru tidak boleh dipasangkan ke event OPFS lama berjarak > 5 menit.
    old_media = {"kind": "photo", "proxy_path": "/2/dm_conversations/media/xchat/old/img_old.jpg"}
    new_media = {"kind": "photo", "proxy_path": "/2/dm_conversations/media/xchat/new/img_new.jpg"}
    decrypted_chronological = [
        {"id": "uuid-old", "sender_id": "777", "text": "yg punya fto ini bagi dong wots",
         "created_at": "2026-11-10T18:27:02.630Z", "_xapi_attachments": [old_media],
         "_xchat_media_state": "ready", "is_outgoing": False},
        {"id": "uuid-new", "sender_id": "777", "text": "yg punya fto ini bagi dong wots",
         "created_at": "2026-11-23T20:15:19.410Z", "_xapi_attachments": [new_media],
         "_xchat_media_state": "ready", "is_outgoing": False},
    ]
    formatted = {
        "data": [
            {"id": "2124960003799052288", "event_type": "MessageCreate", "sender_id": "777",
             "text": "[XChat E2EE Encrypted Message]", "_xchat_encrypted": True,
             "created_at": "2026-11-23T20:15:19.410Z"},
        ],
        "meta": {"result_count": 1},
    }
    with patch("app.routers.dm.resolve_me_id", new=AsyncMock(return_value="999")), \
         patch("app.routers.dm.unlock_and_read_xchat_conversation",
               new=AsyncMock(return_value=decrypted_chronological)):
        out = await _enrich_conv_events_with_e2ee(formatted, "token", "123456", "999-777", max_results=10)
    # Placeholder 23 Nov WAJIB menerima foto 23 Nov, BUKAN foto 10 Nov!
    assert out["data"][0]["_xapi_attachments"] == [new_media]

    # Jika OPFS belum sinkron (hanya punya event 10 Nov), placeholder 23 Nov
    # TIDAK boleh mengambil foto 10 Nov via positional fallback!
    formatted_unsynced = {
        "data": [
            {"id": "2124960003799052288", "event_type": "MessageCreate", "sender_id": "777",
             "text": "[XChat E2EE Encrypted Message]", "_xchat_encrypted": True,
             "created_at": "2026-11-23T20:15:19.410Z"},
        ],
        "meta": {"result_count": 1},
    }
    with patch("app.routers.dm.resolve_me_id", new=AsyncMock(return_value="999")), \
         patch("app.routers.dm.unlock_and_read_xchat_conversation",
               new=AsyncMock(return_value=[decrypted_chronological[0]])):
        out2 = await _enrich_conv_events_with_e2ee(formatted_unsynced, "token", "123456", "999-777", max_results=10)
    ph_out = next(e for e in out2["data"] if e["id"] == "2124960003799052288")
    assert ph_out.get("_xapi_attachments") is None


@pytest.mark.asyncio
async def test_recover_opfs_media_prioritizes_newest_under_max_files_cap(monkeypatch):
    """Jika ada >max_files event bermedia dalam percakapan, recover_opfs_media_for_events
    WAJIB memulihkan event TERBARU lebih dulu, bukan menghabiskan kuota pada foto lama."""
    import sqlite3
    import app.xchat_e2ee as xee

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE dm_local_attachment (
            attachment_id TEXT, file_number INTEGER, local_path TEXT,
            downloaded_at INTEGER, file_size INTEGER, conversation_id TEXT,
            message_id TEXT, attachment_type TEXT, mime_type TEXT, metadata TEXT
        )
    """)
    rows = []
    for i in range(5):
        eid = f"ev-{i}"
        ts = 1795000000000 + i * 60_000
        rows.append({
            "entry_id": eid, "timestamp": ts, "sender_id": 777,
            "plain_text": "yg punya fto ini bagi dong wots", "has_attachment": 1,
            "message_status": "Sent", "deleted": 0, "event_type": None,
            "attachment_types": "media", "contents": b"attachmentId\x00x",
        })
        conn.execute(
            "INSERT INTO dm_local_attachment VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"a-{i}", 1, f"p/{eid}.jpg", 1, 10, "1:2", eid, "MediaImage", None, None),
        )
    # query_dm_entries mengembalikan terbaru-dulu -> project_dm_entries_to_events membalik kronologis
    rows_desc = list(reversed(rows))
    events = xee.project_dm_entries_to_events(rows_desc, "1-2")
    monkeypatch.setattr(
        xee, "read_xchat_opfs_file", AsyncMock(return_value=b"\xff\xd8\xff\xe0" + b"X" * 300)
    )
    await xee.recover_opfs_media_for_events(conn, None, None, rows_desc, events, max_files=2)
    conn.close()

    by_id = {e["id"]: e for e in events}
    # 2 event TERBARU (ev-4 & ev-3) harus ready; yang lama tetap pending
    assert by_id["ev-4"]["_xchat_media_state"] == "ready"
    assert by_id["ev-3"]["_xchat_media_state"] == "ready"
    assert by_id["ev-0"].get("_xchat_media_pending") is True


def test_cache_e2ee_media_hashes_full_bytes_not_only_header():
    import base64
    from app.xchat_e2ee import _E2EE_MEDIA_CACHE, cache_e2ee_media

    _E2EE_MEDIA_CACHE.clear()
    same_header = b"\xff\xd8\xff\xe0" + b"\x00" * 300
    img1 = "data:image/jpeg;base64," + base64.b64encode(same_header + b"PHOTO_ONE").decode()
    img2 = "data:image/jpeg;base64," + base64.b64encode(same_header + b"PHOTO_TWO").decode()
    d1 = cache_e2ee_media(img1, key_hint="same_hint", kind="photo")
    d2 = cache_e2ee_media(img2, key_hint="same_hint", kind="photo")
    assert d1 is not None and d2 is not None
    assert d1["media_id"] != d2["media_id"]
    _E2EE_MEDIA_CACHE.clear()


def test_is_recent_pending_media_skips_ancient_backlog():
    from app.xchat_e2ee import _is_recent_pending_media

    now_ms = 1795500000000
    fresh_ev = {"_xchat_media_pending": True, "created_at": "2026-11-24T00:00:00.000Z"}
    ancient_ev = {"_xchat_media_pending": True, "created_at": "2025-06-09T09:40:19.542Z"}
    # Pastikan memakai timestamp dekat now_ms
    from datetime import datetime, timezone
    fresh_ev["created_at"] = datetime.fromtimestamp(
        (now_ms - 3600_000) / 1000, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert _is_recent_pending_media(fresh_ev, now_ms=now_ms, max_age_hours=48.0) is True
    assert _is_recent_pending_media(ancient_ev, now_ms=now_ms, max_age_hours=48.0) is False
    assert "allMatching.length - 1 - rankFromNewest" in _EXTRACT_MEDIA_JS

