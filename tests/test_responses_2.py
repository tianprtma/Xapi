"""More tests for app/responses.py — finalize, wrap, stub_501, _strip_sensitive."""

from __future__ import annotations

import json

from app.responses import (
    _strip_sensitive,
    _upstream_error_status,
    wrap,
    finalize,
    write_finalize,
    stub_501,
    batch_finalize,
)


def resp_json(response):
    return json.loads(response.body.decode())


class TestStripSensitive:
    def test_strips_cookies(self):
        r = _strip_sensitive({"status": "ok", "cookies": {"a": "b"}, "data": {}})
        assert "cookies" not in r
        assert r["status"] == "ok"

    def test_strips_tokens(self):
        r = _strip_sensitive({"status": "ok", "tokens": {"at": "123"}, "data": {}})
        assert "tokens" not in r

    def test_keeps_other_keys(self):
        r = _strip_sensitive({"status": "ok", "data": {"id": "1"}})
        assert r["data"]["id"] == "1"

    def test_empty(self):
        assert _strip_sensitive({}) == {}


class TestWrap:
    def test_ok_map_200(self):
        resp = wrap({"status": "ok", "data": {"id": "1"}, "cookies": {"a": "b"}})
        assert resp.status_code == 200
        body = resp_json(resp)
        assert "cookies" not in body
        assert body["data"]["id"] == "1"

    def test_invalid_map_401(self):
        resp = wrap({"status": "invalid"})
        assert resp.status_code == 401

    def test_error_map_502(self):
        resp = wrap({"status": "error"})
        assert resp.status_code == 502

    def test_unknown_status_map_500(self):
        resp = wrap({"status": "unknown"})
        assert resp.status_code == 500

    def test_no_status_map_500(self):
        resp = wrap({})
        assert resp.status_code == 500


class TestFinalize:
    def test_success_with_formatter(self):
        result = {"status": "ok", "data": {"user": {"id": "1"}}}
        resp = finalize(result, lambda d: {"data": d.get("user")}, raw=False)
        assert resp.status_code == 200
        assert resp_json(resp)["data"]["id"] == "1"

    def test_raw_mode(self):
        result = {"status": "ok", "cookies": {"a": "b"}}
        resp = finalize(result, lambda d: {"data": d}, raw=True)
        assert "cookies" not in resp_json(resp)

    def test_invalid_status(self):
        result = {"status": "invalid", "error": "expired"}
        resp = finalize(result, lambda d: {"data": d}, raw=False)
        assert resp.status_code == 401

    def test_error_status(self):
        result = {"status": "error", "http_status": 502, "error": "upstream down"}
        resp = finalize(result, lambda d: {"data": d}, raw=False)
        assert resp.status_code == 502

    def test_formatter_detects_error_syntax(self):
        result = {"status": "ok", "data": {"errors": [{"title": "Not Found"}], "data": None}}
        resp = finalize(result, lambda d: d, raw=False)
        # Has errors and no data → 404
        assert resp.status_code == 404


class TestWriteFinalize:
    def test_raw_strips_sensitive(self):
        result = {"status": "ok", "cookies": {"a": "b"}, "tokens": {"t": "1"}}
        resp = write_finalize(result, raw=True)
        body = resp_json(resp)
        assert "cookies" not in body
        assert "tokens" not in body

    def test_invalid_with_detail(self):
        result = {"status": "invalid", "error": "session died", "http_status": 403}
        resp = write_finalize(result, raw=False)
        assert resp.status_code == 401
        # UPSTREAM_AUTH_REJECTED for 403
        assert "session died" in resp_json(resp)["errors"][0]["detail"]

    def test_error_fallback(self):
        result = {"status": "error", "http_status": 503}
        resp = write_finalize(result, raw=False)
        assert resp.status_code == 503


class TestStub501:
    def test_basic(self):
        resp = stub_501("test_feature", "not implemented yet")
        assert resp.status_code == 501
        body = resp_json(resp)
        assert body["errors"][0]["feature"] == "test_feature"

    def test_with_suggestion(self):
        resp = stub_501("test", "nope", suggestion="use /other")
        body = resp_json(resp)
        assert body["errors"][0]["suggestion"] == "use /other"

    def test_with_docs(self):
        resp = stub_501("test", "nope", docs="https://x.com")
        body = resp_json(resp)
        assert body["errors"][0]["docs"] == "https://x.com"


class TestBatchFinalize:
    def test_success(self):
        resp = batch_finalize({"data": [{"id": "1"}], "meta": {"result_count": 1}})
        assert resp.status_code == 200

    def test_no_data_404(self):
        resp = batch_finalize({"errors": [{"title": "Not Found"}]})
        assert resp.status_code == 404

    def test_empty_dict(self):
        resp = batch_finalize({})
        assert resp.status_code == 200


class TestUpstreamErrorStatus:
    def test_known_401_code(self):
        assert _upstream_error_status({"code": 32}) == 401
        assert _upstream_error_status({"code": 64}) == 401
        assert _upstream_error_status({"code": 89}) == 401

    def test_permission_text(self):
        assert _upstream_error_status({"message": "You are not permitted"}) == 403

    def test_not_found_code(self):
        assert _upstream_error_status({"code": 34}) == 404
        assert _upstream_error_status({"code": 50}) == 404
        assert _upstream_error_status({"code": 144}) == 404

    def test_not_found_text(self):
        assert _upstream_error_status({"message": "resource does not exist"}) == 404

    def test_validation_text(self):
        assert _upstream_error_status({"message": "Bad request"}) == 400
        assert _upstream_error_status({"message": "validation failed"}) == 400

    def test_unknown_fallback(self):
        assert _upstream_error_status({"message": "something else"}) == 502
