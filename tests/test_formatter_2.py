"""Tests for formatter.py — all normalizers with realistic GraphQL shapes."""

from __future__ import annotations

import json

from formatter import (
    _user_result_to_obj,
    _tweet_result_to_obj,
    format_user,
    format_tweet,
    format_tweet_collection,
    format_community,
    format_bookmark_folders,
    format_dm_send_result,
    format_birdwatch_note_result,
    format_birdwatch_notes_slice,
    format_birdwatch_batsignal,
    format_error,
)

# ──────────────── User formatter ────────────────


class TestUserResultToObj:
    def test_minimal(self):
        u = {"rest_id": "123", "core": {"screen_name": "foo"}, "legacy": {}}
        obj = _user_result_to_obj(u)
        assert obj is not None
        assert obj["id"] == "123"
        assert obj["username"] == "foo"

    def test_none(self):
        assert _user_result_to_obj(None) is None

    def test_unavailable(self):
        assert _user_result_to_obj({"__typename": "UserUnavailable"}) is None

    def test_full(self):
        u = {
            "rest_id": "44196397",
            "is_blue_verified": True,
            "core": {
                "name": "Elon",
                "screen_name": "elonmusk",
                "created_at": "Tue Jun 01 12:00:00 +0000 2010",
            },
            "legacy": {
                "description": "desc",
                "followers_count": 100,
                "friends_count": 50,
                "statuses_count": 200,
                "listed_count": 10,
                "favourites_count": 500,
                "media_count": 20,
                "profile_image_url_https": "https://example.com/pic.jpg",
                "verified": False,
                "protected": False,
                "location": "Mars",
                "url": "https://x.com",
            },
        }
        obj = _user_result_to_obj(u)
        assert obj["name"] == "Elon"
        assert obj["public_metrics"]["followers_count"] == 100
        assert obj["verified"] is True  # is_blue_verified overrides


class TestFormatUser:
    def test_success(self):
        gql = {
            "data": {
                "user": {
                    "result": {
                        "rest_id": "123",
                        "core": {"name": "A", "screen_name": "a"},
                        "legacy": {},
                    }
                }
            }
        }
        out = format_user(gql)
        assert out["data"]["id"] == "123"

    def test_not_found(self):
        out = format_user({"data": {"user": {"result": None}}})
        assert "errors" in out
        assert out["errors"][0]["title"] == "Not Found"

    def test_empty(self):
        assert format_user({})["errors"][0]["title"] == "Not Found"


# ──────────────── Tweet formatter ────────────────


class TestTweetResultToObj:
    def test_minimal(self):
        t = {"rest_id": "999", "core": {}, "legacy": {"full_text": "hello"}}
        obj = _tweet_result_to_obj(t)
        assert obj is not None
        assert obj["id"] == "999"
        assert obj["text"] == "hello"

    def test_none(self):
        assert _tweet_result_to_obj(None) is None

    def test_tombstone(self):
        assert _tweet_result_to_obj({"__typename": "TweetTombstone"}) is None

    def test_visibility_wrapper(self):
        t = {
            "__typename": "TweetWithVisibilityResults",
            "tweet": {
                "rest_id": "888",
                "core": {},
                "legacy": {"full_text": "visible"},
            },
        }
        obj = _tweet_result_to_obj(t)
        assert obj["id"] == "888"

    def test_note_tweet(self):
        t = {
            "rest_id": "777",
            "core": {},
            "note_tweet": {
                "note_tweet_results": {
                    "result": {"text": "long note text"}
                }
            },
            "legacy": {},
        }
        obj = _tweet_result_to_obj(t)
        assert obj["text"] == "long note text"

    def test_entities(self):
        t = {
            "rest_id": "111",
            "core": {},
            "legacy": {
                "full_text": "tweet",
                "entities": {
                    "hashtags": [{"text": "tag1"}],
                    "user_mentions": [{"screen_name": "u", "id_str": "1"}],
                    "urls": [{"url": "https://t.co/x", "expanded_url": "https://x.com", "display_url": "x.com"}],
                    "symbols": [{"text": "BTC"}],
                },
                "extended_entities": {"media": [{"media_key": "3_123"}]},
            },
        }
        obj = _tweet_result_to_obj(t)
        assert len(obj["entities"]["hashtags"]) == 1
        assert obj["entities"]["hashtags"][0]["tag"] == "tag1"
        assert len(obj["attachments"]["media_keys"]) == 1


class TestFormatTweet:
    def test_tweet_result_path(self):
        gql = {
            "data": {
                "tweetResult": {
                    "result": {
                        "rest_id": "1",
                        "core": {"user_results": {"result": {"rest_id": "2", "core": {}, "legacy": {}}}},
                        "legacy": {"full_text": "hi"},
                    }
                }
            }
        }
        out = format_tweet(gql)
        assert out["data"]["id"] == "1"

    def test_create_tweet_path(self):
        gql = {
            "data": {
                "create_tweet": {
                    "tweet_results": {
                        "result": {"rest_id": "3", "core": {}, "legacy": {"full_text": "new"}}
                    }
                }
            }
        }
        out = format_tweet(gql)
        assert out["data"]["id"] == "3"

    def test_not_found(self):
        out = format_tweet({})
        assert "errors" in out


# ──────────────── Timeline formatter ────────────────


class TestFormatTweetCollection:
    SAMPLE_GQL = {
        "data": {
            "home": {
                "home_timeline_urt": {
                    "instructions": [
                        {
                            "type": "TimelineAddEntries",
                            "entries": [
                                {
                                    "content": {
                                        "entryType": "TimelineTimelineItem",
                                        "itemContent": {
                                            "itemType": "TimelineTweet",
                                            "tweet_results": {
                                                "result": {
                                                    "rest_id": "10",
                                                    "core": {},
                                                    "legacy": {"full_text": "t1"},
                                                }
                                            },
                                        },
                                    },
                                },
                                {
                                    "content": {
                                        "entryType": "TimelineTimelineCursor",
                                        "cursorType": "Bottom",
                                        "value": "cursor123",
                                    },
                                },
                            ],
                        },
                    ]
                }
            }
        }
    }

    def test_tweets(self):
        out = format_tweet_collection(self.SAMPLE_GQL, item="tweet")
        assert len(out["data"]) == 1
        assert out["data"][0]["id"] == "10"
        assert out["meta"]["next_token"] == "cursor123"

    def test_empty(self):
        out = format_tweet_collection({})
        assert out["data"] == []
        assert out["meta"]["result_count"] == 0

    def test_pin_entry(self):
        gql = {
            "data": {
                "user": {
                    "result": {
                        "timeline_v2": {
                            "timeline": {
                                "instructions": [
                                    {
                                        "type": "TimelinePinEntry",
                                        "entry": {
                                            "content": {
                                                "itemContent": {
                                                    "itemType": "TimelineTweet",
                                                    "tweet_results": {
                                                        "result": {
                                                            "rest_id": "99",
                                                            "core": {},
                                                            "legacy": {"full_text": "pinned"},
                                                        }
                                                    },
                                                },
                                            },
                                        },
                                    },
                                ]
                            }
                        }
                    }
                }
            }
        }
        out = format_tweet_collection(gql)
        assert len(out["data"]) == 1


# ──────────────── Community ────────────────


class TestFormatCommunity:
    def test_basic(self):
        gql = {
            "data": {
                "communityResults": {
                    "result": {
                        "rest_id": "c1",
                        "name": "TestComm",
                        "description": "desc",
                        "member_count": 10,
                        "actions": {},
                        "rules": [{"rest_id": "r1", "name": "r1", "description": "d"}],
                    }
                }
            }
        }
        out = format_community(gql)
        assert out["data"]["id"] == "c1"
        assert out["data"]["name"] == "TestComm"

    def test_not_found(self):
        out = format_community({})
        assert "errors" in out

    def test_wrong_typename(self):
        gql = {"data": {"communityResults": {"result": {"__typename": "SomethingElse"}}}}
        out = format_community(gql)
        assert "errors" in out


# ──────────────── Bookmark folders ────────────────


class TestFormatBookmarkFolders:
    def test_basic(self):
        gql = {
            "data": {
                "viewer": {
                    "user_results": {
                        "result": {
                            "bookmark_collections_slice": {
                                "items": [
                                    {"id": "f1", "name": "Folder1", "tweet_count": 5},
                                ],
                                "slice_info": {"next_cursor": "n1"},
                            }
                        }
                    }
                }
            }
        }
        out = format_bookmark_folders(gql)
        assert len(out["data"]) == 1
        assert out["data"][0]["name"] == "Folder1"
        assert out["meta"]["next_token"] == "n1"

    def test_empty(self):
        out = format_bookmark_folders({})
        assert out["data"] == []


# ──────────────── DM send result ────────────────


class TestFormatDmSendResult:
    def test_event_path(self):
        payload = {
            "event": {
                "id": "ev1",
                "type": "message_create",
                "message_create": {
                    "target": {"conversation_id": "conv1"},
                    "message_data": {"text": "hi"},
                },
                "created_timestamp": "1700000000000",
            }
        }
        out = format_dm_send_result(payload)
        assert "data" in out
        assert out["data"]["dm_event_id"] == "ev1"

    def test_fallback(self):
        payload = {
            "user_events": {
                "entries": [
                    {
                        "message_create": {
                            "id": "ev2",
                            "type": "message_create",
                            "created_timestamp": "1700000000000",
                        }
                    }
                ]
            }
        }
        out = format_dm_send_result(payload)
        assert "data" in out

    def test_empty(self):
        out = format_dm_send_result({})
        assert out == {"data": {}}


# ──────────────── Birdwatch ────────────────


class TestFormatBirdwatch:
    def test_create_note(self):
        gql = {
            "data": {
                "birdwatchnote_create_v2": {
                    "id": "n1",
                    "data_v1": "some data",
                }
            }
        }
        out = format_birdwatch_note_result(gql)
        assert out["data"]["id"] == "n1"

    def test_note_error(self):
        gql = {
            "data": {
                "birdwatchnote_create_v2": {
                    "__typename": "BirdwatchError",
                    "reason": "rate limited",
                }
            }
        }
        out = format_birdwatch_note_result(gql)
        assert "errors" in out

    def test_notes_slice(self):
        gql = {
            "data": {
                "birdwatch_profile_by_alias": {
                    "notes_slice": {
                        "notes": [
                            {
                                "rest_id": "n1",
                                "classification": "not_misleading",
                                "status": "current",
                            }
                        ],
                        "slice_info": {"next_cursor": "c1"},
                    }
                }
            }
        }
        out = format_birdwatch_notes_slice(gql)
        assert len(out["data"]) == 1
        assert out["meta"]["next_token"] == "c1"

    def test_batsignal(self):
        gql = {
            "data": {
                "birdwatchbatsignal": {
                    "posts": [{"id": "p1"}],
                }
            }
        }
        out = format_birdwatch_batsignal(gql)
        assert len(out["data"]) == 1


# ──────────────── Error wrapper ────────────────


class TestFormatError:
    def test_basic(self):
        out = format_error("Not Found", "tweet not found", "not_found", 404)
        assert out["errors"][0]["title"] == "Not Found"
        assert out["errors"][0]["status"] == 404

    def test_defaults(self):
        out = format_error("Err")
        assert out["errors"][0]["status"] == 500
