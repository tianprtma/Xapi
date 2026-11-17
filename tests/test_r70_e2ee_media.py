import pytest
from unittest.mock import AsyncMock, patch

from app.routers.dm import _enrich_conv_events_with_e2ee
from app.xchat_e2ee import _E2EE_MEDIA_CACHE, project_xchat_message_rows


def test_xchat_row_projection_marks_attachment_focus_pending():
    events = project_xchat_message_rows([{
        "row_key": "row-photo",
        "sender_id": "777",
        "text": "wots gambar",
        "image_data_urls": [],
        "media_pending": True,
    }], "999-777")
    assert events[0]["_xchat_media_pending"] is True
    assert events[0]["_xchat_media_state"] == "pending"
    assert "_xapi_attachments" not in events[0]


def test_xchat_text_only_row_is_explicitly_media_free():
    events = project_xchat_message_rows([{
        "row_key": "row-text",
        "sender_id": "777",
        "text": "wots teks saja",
        "image_data_urls": [],
        "media_pending": False,
        "media_state": "none",
    }], "999-777")
    assert events[0]["_xchat_media_state"] == "none"
    assert not events[0].get("_xchat_media_pending")


def test_xchat_row_projection_emits_cached_media():
    _E2EE_MEDIA_CACHE.clear()
    events = project_xchat_message_rows([{
        "row_key": "row-photo-ok",
        "sender_id": "777",
        "text": "wots gambar",
        "image_data_urls": ["data:image/jpeg;base64,/9j/2Q=="],
        "media_pending": False,
    }], "999-777")
    assert events[0]["_xapi_attachments"][0]["proxy_path"].startswith(
        "/2/dm_conversations/media/xchat/"
    )
    assert "_xchat_media_pending" not in events[0]
    _E2EE_MEDIA_CACHE.clear()


@pytest.mark.asyncio
async def test_plain_uuid_event_without_dom_result_stays_pending():
    formatted = {"data": [{"id": "uuid-plain", "event_type": "MessageCreate",
                           "sender_id": "777", "text": "wots gambar"}], "meta": {}}
    with patch("app.routers.dm.resolve_me_id", new=AsyncMock(return_value="999")), \
         patch("app.routers.dm.unlock_and_read_xchat_conversation", new=AsyncMock(return_value=[])):
        out = await _enrich_conv_events_with_e2ee(formatted, "token", "123456", "999-777")
    assert out["data"][0]["_xchat_media_pending"] is True


@pytest.mark.asyncio
async def test_plain_uuid_event_keeps_pending_marker_after_extraction_failure():
    formatted = {"data": [{"id": "uuid-failed", "event_type": "MessageCreate",
                           "sender_id": "777", "text": "wots gambar"}], "meta": {}}
    pending = [{"id": "uuid-failed", "sender_id": "777", "text": "wots gambar",
                "_xchat_media_pending": True, "_xchat_media_state": "pending"}]
    with patch("app.routers.dm.resolve_me_id", new=AsyncMock(return_value="999")), \
         patch("app.routers.dm.unlock_and_read_xchat_conversation",
               new=AsyncMock(return_value=pending)):
        out = await _enrich_conv_events_with_e2ee(formatted, "token", "123456", "999-777")
    assert out["data"][0]["_xchat_media_pending"] is True


@pytest.mark.asyncio
async def test_plain_uuid_event_with_pending_media_triggers_e2ee_enrichment():
    media = {"kind": "photo", "proxy_path": "/2/dm_conversations/media/xchat/m1/img_m1.jpg"}
    formatted = {"data": [{"id": "uuid-plain", "event_type": "MessageCreate",
                             "sender_id": "777", "text": "wots gambar", "created_at": None}],
                 "meta": {"result_count": 1}}
    decrypted = [{"id": "uuid-plain", "sender_id": "777", "text": "wots gambar",
                  "_xapi_attachments": [media], "is_outgoing": False}]
    with patch("app.routers.dm.resolve_me_id", new=AsyncMock(return_value="999")), \
         patch("app.routers.dm.unlock_and_read_xchat_conversation",
               new=AsyncMock(return_value=decrypted)) as unlock:
        out = await _enrich_conv_events_with_e2ee(formatted, "token", "123456", "999-777")
    unlock.assert_awaited_once()
    assert out["data"][0]["_xapi_attachments"] == [media]


@pytest.mark.asyncio
async def test_e2ee_enrichment_unlocks_when_older_event_is_encrypted():
    media = {"kind": "photo", "proxy_path": "/2/dm_conversations/media/xchat/m1/img_m1.jpg"}
    formatted = {
        "data": [
            {"id": "new", "event_type": "MessageCreate", "text": "plain newest"},
            {"id": "old", "event_type": "MessageCreate", "text": "[XChat E2EE Encrypted Message]",
             "sender_id": "777"},
        ],
        "meta": {"result_count": 2},
    }
    decrypted = [
        {"id": "uuid-new", "sender_id": "999", "text": "plain newest", "is_outgoing": True},
        {"id": "uuid-old", "sender_id": "777", "text": "wots gambar",
         "_xapi_attachments": [media], "is_outgoing": False},
    ]
    with patch("app.routers.dm.resolve_me_id", new=AsyncMock(return_value="999")), \
         patch("app.routers.dm.unlock_and_read_xchat_conversation",
               new=AsyncMock(return_value=decrypted)) as unlock:
        out = await _enrich_conv_events_with_e2ee(
            formatted, "token", "123456", "999-777", max_results=10
        )

    unlock.assert_awaited_once()
    assert any(e.get("text") == "wots gambar" and e.get("_xapi_attachments") == [media]
               for e in out["data"])
