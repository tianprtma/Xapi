import pytest
from unittest.mock import AsyncMock, patch

from app.routers.dm import _enrich_conv_events_with_e2ee


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
