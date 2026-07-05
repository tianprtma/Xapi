"""Tests for app/clients.py — graphql_call, rest_call, dm_call, media_upload, helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients import (
    build_dm_new2_payload,
    dm_conv_id_for,
    _invalid_token_response,
)


class TestDmConvIdFor:
    def test_sorted_numeric(self):
        result = dm_conv_id_for("200", "100")
        assert result == "100-200"

    def test_reversed(self):
        result = dm_conv_id_for("100", "200")
        assert result == "100-200"

    def test_non_numeric(self):
        result = dm_conv_id_for("abc", "xyz")
        # falls back to string sort
        assert "-" in result

    def test_mixed(self):
        result = dm_conv_id_for("100", "abc")
        assert result == "100-abc"


class TestBuildDmNew2Payload:
    def test_minimal(self):
        p = build_dm_new2_payload(me="1", conv_id=None, recipient_ids=["2"], text="hi")
        assert p["text"] == "hi"
        assert p["recipient_ids"] == "2"
        assert "conversation_id" not in p

    def test_with_conv_id(self):
        p = build_dm_new2_payload(me="1", conv_id="1-2", recipient_ids=None, text="hi")
        assert p["conversation_id"] == "1-2"
        assert "recipient_ids" not in p

    def test_with_media(self):
        p = build_dm_new2_payload(me="1", conv_id=None, recipient_ids=["2"], text="hi", media_id="m1")
        assert p["media_id"] == "m1"

    def test_with_reply(self):
        p = build_dm_new2_payload(me="1", conv_id=None, recipient_ids=["2"], text="hi", reply_to="e1")
        assert p["reply_to_dm_id"] == "e1"

    def test_multiple_recipients(self):
        p = build_dm_new2_payload(me="1", conv_id=None, recipient_ids=["2", "3"], text="hi")
        assert p["recipient_ids"] == "2,3"


class TestInvalidTokenResponse:
    class FakeInvalidTokenError(Exception):
        def __init__(self, http_status=401, message="bad token", jar={"a": "b"}, ct0="ct0_val"):
            self.http_status = http_status
            self.message = message
            self.jar = jar
            self.ct0 = ct0

    def test_returns_status_invalid(self):
        e = self.FakeInvalidTokenError()
        r = _invalid_token_response(e, "tok123")
        assert r["status"] == "invalid"
        assert r["http_status"] == 401
        assert r["error"] == "bad token"
        # No cookies/tokens in response (security fix)
        assert "cookies" not in r
        assert "tokens" not in r
