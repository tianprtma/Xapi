"""Unit tests for app.errors — error code catalog."""

from app.errors import (
    ERROR_CODES,
    ErrorCode,
    build_error,
    build_error_jsonapi,
)


class TestErrorCodes:
    def test_all_error_codes_have_required_fields(self):
        """Every ErrorCode must have code, title, http_status, detail_template."""
        for key, ec in ERROR_CODES.items():
            assert isinstance(ec, ErrorCode)
            assert ec.code == key, f"{key}: code mismatch"
            assert ec.title, f"{key}: missing title"
            assert isinstance(ec.http_status, int), f"{key}: http_status must be int"
            assert 400 <= ec.http_status <= 599, f"{key}: http_status out of range"
            assert ec.detail_template, f"{key}: missing detail_template"

    def test_error_codes_are_unique_per_http_status_and_title(self):
        """No two error codes should share both http_status and title."""
        seen = set()
        for ec in ERROR_CODES.values():
            pair = (ec.http_status, ec.title)
            assert pair not in seen, f"Duplicate (status,title): {pair}"
            seen.add(pair)

    def test_auth_errors_are_401(self):
        for key in ERROR_CODES:
            if key.startswith("AUTH_"):
                assert ERROR_CODES[key].http_status == 401, key

    def test_upstream_errors_are_401_502_or_504(self):
        for key in ERROR_CODES:
            if key.startswith("UPSTREAM_"):
                assert ERROR_CODES[key].http_status in (401, 502, 504), key

    def test_rate_errors_are_429(self):
        for key in ERROR_CODES:
            if key.startswith("RATE_"):
                assert ERROR_CODES[key].http_status == 429, key

    def test_validation_errors_are_4xx(self):
        for key in ERROR_CODES:
            if key.startswith("VALIDATION_"):
                assert 400 <= ERROR_CODES[key].http_status < 500, key

    def test_infra_errors_are_4xx_or_5xx(self):
        for key in ERROR_CODES:
            if key.startswith("INFRA_"):
                assert 400 <= ERROR_CODES[key].http_status < 600, key


class TestBuildError:
    def test_build_error_returns_correct_structure(self):
        result = build_error("AUTH_TOKEN_MISSING")
        assert "errors" in result
        assert isinstance(result["errors"], list)
        assert len(result["errors"]) == 1
        err = result["errors"][0]
        assert err["code"] == "AUTH_TOKEN_MISSING"
        assert err["title"] == "Authentication Required"
        assert err["status"] == 401

    def test_build_error_with_format_kwargs(self):
        result = build_error("VALIDATION_BODY_SIZE", max_bytes=1048576)
        err = result["errors"][0]
        assert "1048576" in err["detail"]

    def test_build_error_with_custom_detail(self):
        result = build_error("AUTH_TOKEN_EXPIRED", detail="custom detail override")
        assert result["errors"][0]["detail"] == "custom detail override"

    def test_build_error_unknown_key_falls_back_to_internal(self):
        result = build_error("NONEXISTENT_KEY")
        assert result["errors"][0]["code"] == "INFRA_INTERNAL_ERROR"

    def test_build_error_jsonapi_structure(self):
        result = build_error_jsonapi("INFRA_NOT_FOUND", method="GET", path="/2/typo")
        err = result["errors"][0]
        assert "GET" in err["detail"]
        assert "/2/typo" in err["detail"]
        assert err["code"] == "INFRA_NOT_FOUND"
