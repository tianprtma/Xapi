"""R100 — link tweet yang dibagikan sender ikut terposting (jalur OPFS).

KASUS NYATA (20 Nov, conv 1323847942906675200): sender kirim menfess teks +
share tweet (attachment Post, url https://x.com/jidanfreychuu/status/2122725532957835467).
Menfess terposting TANPA link tweet. Proyeksi OPFS R87 hanya membaca plain_text;
link tweet tersimpan sebagai attachment Post di contents BLOB, tidak di plain_text
→ hilang. Bot sudah meng-append `status_links` ke teks post (quote card), jadi
cukup ekstrak URL Post dari contents ke event["status_links"].

Kontrak (R100):
- project_dm_entries_to_events mengekstrak URL tweet (x.com/twitter.com /status/)
  dari contents BLOB ke event["status_links"].
- URL bersih (tanpa tracking ?a=&s=), tanpa garbage biner contents.
- Tanpa Post link → tidak ada status_links.
"""
import app.xchat_e2ee as xee


def _row(contents: bytes, text="wots sedih ya"):
    return {
        "entry_id": "9bad2ed3-8cfe-40d0-95e2-773ed59fba9f",
        "timestamp": 1795156530015, "sender_id": 1323847942906675200,
        "plain_text": text, "has_attachment": 1, "message_status": "Sent",
        "deleted": 0, "event_type": None, "attachment_types": "link",
        "contents": contents,
    }


def test_extracts_post_tweet_link_from_contents():
    contents = (
        b"\x9fx'com.x.models.dm.DmEntryContents.Message"
        b"dtextxQwots sedih ya(kattachments"
        b"x-com.x.models.dm.DmMessageEntryAttachment.Post"
        b"lattachmentIdbidx$78A91140fpostIdevalue"
        b"curlxQhttps://x.com/jidanfreychuu/status/2122725532957835467?a=s7JeBlsnNKT7NHJGX9o&s=61"
        b"\xff\xff\xffvconversationKeyVersionm1795156530015"
    )
    events = xee.project_dm_entries_to_events([_row(contents)], "1323847942906675200-1394249284736864258")
    links = events[0].get("status_links") or []
    assert "https://x.com/jidanfreychuu/status/2122725532957835467" in links, links
    # tidak boleh membawa garbage biner / tracking
    assert all("\xff" not in l and "?a=" not in l for l in links)


def test_no_post_link_no_status_links():
    contents = b"\x9fx'com.x.models.dm.DmEntryContents.MessagedtextxQwots sedih ya"
    events = xee.project_dm_entries_to_events([_row(contents)], "1-2")
    assert not events[0].get("status_links")


def test_twitter_com_link_also_extracted():
    contents = b"curlxQhttps://twitter.com/someone/status/1234567890?s=20\xff\xff"
    events = xee.project_dm_entries_to_events([_row(contents)], "1-2")
    links = events[0].get("status_links") or []
    assert "https://twitter.com/someone/status/1234567890" in links


def test_video_permalink_suffix_preserved():
    # R103: sender share link /video/1 — sufiks WAJIB utuh agar X render kartu
    # video inline, bukan quote tweet. Kasus nyata conv 930812366488403968.
    contents = b"curlx9https://x.com/viiccc89/status/2123778200404987934/video/1\xff\xff"
    events = xee.project_dm_entries_to_events([_row(contents)], "1-2")
    links = events[0].get("status_links") or []
    assert "https://x.com/viiccc89/status/2123778200404987934/video/1" in links, links


def test_photo_permalink_suffix_preserved():
    contents = b"curlx9https://x.com/someone/status/1234567890/photo/1\xff\xff"
    events = xee.project_dm_entries_to_events([_row(contents)], "1-2")
    links = events[0].get("status_links") or []
    assert "https://x.com/someone/status/1234567890/photo/1" in links, links


def test_bare_status_link_still_bare():
    contents = b"curlxQhttps://x.com/someone/status/1234567890?s=20\xff\xff"
    events = xee.project_dm_entries_to_events([_row(contents)], "1-2")
    links = events[0].get("status_links") or []
    assert "https://x.com/someone/status/1234567890" in links
    assert all("/video/" not in l and "/photo/" not in l for l in links)