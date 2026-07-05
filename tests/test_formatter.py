"""Unit tests for formatter — GQL → X API v2 normalizers."""

import pytest
from formatter import (
    _user_result_to_obj,
    _tweet_result_to_obj,
    format_user,
    format_tweet_collection,
    format_error,
)


class TestUserNormalizer:
    def test_user_result_to_obj_minimal(self):
        """Minimal valid user_result with legacy fields."""
        ur = {
            "rest_id": "123",
            "legacy": {
                "name": "Test User",
                "screen_name": "testuser",
                "followers_count": 100,
                "friends_count": 50,
                "statuses_count": 10,
            },
        }
        obj = _user_result_to_obj(ur)
        assert obj is not None
        assert obj["id"] == "123"
        assert obj["name"] == "Test User"
        assert obj["username"] == "testuser"
        assert obj["public_metrics"]["followers_count"] == 100
        assert obj["public_metrics"]["following_count"] == 50
        assert obj["public_metrics"]["tweet_count"] == 10

    def test_user_result_to_obj_none_input(self):
        assert _user_result_to_obj(None) is None
        assert _user_result_to_obj({}) is None

    def test_user_result_to_obj_unavailable(self):
        ur = {"__typename": "UserUnavailable"}
        assert _user_result_to_obj(ur) is None

    def test_user_result_to_obj_with_core_fields(self):
        """Core fields (X v2) take precedence over legacy."""
        ur = {
            "rest_id": "456",
            "legacy": {"name": "Legacy Name", "screen_name": "legacy"},
            "core": {"name": "Core Name", "screen_name": "core_user", "created_at": "2020-01-01"},
        }
        obj = _user_result_to_obj(ur)
        assert obj["name"] == "Core Name"
        assert obj["username"] == "core_user"
        assert obj["created_at"] == "2020-01-01"

    def test_user_result_to_obj_verified(self):
        ur = {
            "rest_id": "789",
            "legacy": {"verified": True},
            "is_blue_verified": True,
        }
        obj = _user_result_to_obj(ur)
        assert obj["verified"] is True

    def test_format_user_not_found(self):
        """format_user should return {errors: [...]} on missing user."""
        result = format_user({})
        assert "errors" in result
        assert result["errors"][0]["type"] == "not_found"


class TestTweetNormalizer:
    def test_tweet_result_to_obj_minimal(self):
        tr = {
            "rest_id": "111",
            "legacy": {
                "full_text": "hello world",
                "created_at": "2024-01-01T00:00:00Z",
                "user_id_str": "999",
                "conversation_id_str": "111",
            },
            "core": {
                "user_results": {
                    "result": {"rest_id": "999", "legacy": {"screen_name": "author"}}
                }
            },
        }
        obj = _tweet_result_to_obj(tr)
        assert obj is not None
        assert obj["id"] == "111"
        assert obj["text"] == "hello world"
        assert obj["author_id"] == "999"

    def test_tweet_result_to_obj_none(self):
        assert _tweet_result_to_obj(None) is None
        assert _tweet_result_to_obj({}) is None

    def test_tweet_result_to_obj_tombstone(self):
        assert _tweet_result_to_obj({"__typename": "TweetTombstone"}) is None

    def test_tweet_result_to_obj_visibility_wrapper(self):
        """TweetWithVisibilityResults should unwrap inner tweet."""
        tr = {
            "__typename": "TweetWithVisibilityResults",
            "tweet": {
                "rest_id": "222",
                "legacy": {"full_text": "wrapped tweet", "user_id_str": "888"},
                "core": {"user_results": {"result": {"rest_id": "888", "legacy": {"screen_name": "x"}}}},
            },
        }
        obj = _tweet_result_to_obj(tr)
        assert obj is not None
        assert obj["id"] == "222"
        assert obj["text"] == "wrapped tweet"

    def test_format_tweet_collection(self):
        """format_tweet_collection should return a v2 list shape."""
        raw = {
            "data": {
                "threaded_conversation_with_injections_v2": {
                    "instructions": [
                        {
                            "type": "TimelineAddEntries",
                            "entries": [
                                {
                                    "entryId": "tweet-123",
                                    "content": {
                                        "itemContent": {
                                            "tweet_results": {
                                                "result": {
                                                    "rest_id": "123",
                                                    "legacy": {
                                                        "full_text": "hello",
                                                        "user_id_str": "456",
                                                    },
                                                    "core": {
                                                        "user_results": {
                                                            "result": {
                                                                "rest_id": "456",
                                                                "legacy": {"screen_name": "u"},
                                                            }
                                                        }
                                                    },
                                                }
                                            }
                                        }
                                    },
                                }
                            ],
                        }
                    ]
                }
            }
        }
        result = format_tweet_collection(raw)
        assert "data" in result


class TestFormatError:
    def test_format_error_structure(self):
        result = format_error("Test Title", "test detail", "test_type", 400)
        assert "errors" in result
        assert result["errors"][0]["title"] == "Test Title"
        assert result["errors"][0]["detail"] == "test detail"
        assert result["errors"][0]["type"] == "test_type"
        assert result["errors"][0]["status"] == 400
