from app.xchat_e2ee import _E2EE_MEDIA_CACHE, project_xchat_message_rows


def test_xchat_row_projection_emits_video_attachment():
    from app.xchat_e2ee import _E2EE_MEDIA_CACHE
    _E2EE_MEDIA_CACHE.clear()
    events = project_xchat_message_rows([{
        "row_key": "row-video",
        "sender_id": "777",
        "text": "wots video",
        "video_data_urls": ["data:video/mp4;base64,AAAAFGZ0eXBpc29tZQ=="],
        "video_duration_ms": 12000,
        "video_pending": False,
        "media_state": "ready",
    }], "999-777")
    att = events[0]["_xapi_attachments"][0]
    assert att["kind"] == "video"
    assert att["mime"] == "video/mp4"
    assert att["duration_ms"] == 12000
    assert att["byte_size"] > 0
    assert att["proxy_path"].endswith(".mp4")
    _E2EE_MEDIA_CACHE.clear()


def test_xchat_row_projection_marks_video_pending():
    events = project_xchat_message_rows([{
        "row_key": "row-video-pending", "sender_id": "777", "text": "wots video",
        "video_data_urls": [], "video_pending": True, "media_state": "pending",
    }], "999-777")
    assert events[0]["_xchat_media_pending"] is True
