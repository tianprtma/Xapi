"""Integration tests for Xapi HTTP endpoints.

Tests use FastAPI TestClient — no real X upstream calls.
All external HTTP is mocked. Focus on auth, error codes, headers.
"""

import pytest


class TestInfoEndpoint:
    def test_info_returns_service_metadata(self, app_client):
        resp = app_client.get("/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "X (Twitter) Cookie API"
        assert "version" in data
        assert "worker_id" in data
        assert data["docs"] == "/docs"

    def test_info_no_auth_required(self, app_client):
        resp = app_client.get("/info")
        assert resp.status_code == 200


class TestHealthEndpoint:
    def test_health_returns_result(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "healthy" in data
        assert "checks" in data
        assert "worker_id" in data
        assert "session_cache" in data["checks"]

    def test_health_no_auth_required(self, app_client):
        resp = app_client.get("/health")
        assert resp.status_code in (200, 503)


class TestAuthHeader:
    def test_missing_auth_returns_401(self, app_client):
        resp = app_client.get("/2/users/by/username/testuser")
        assert resp.status_code == 401

    def test_invalid_token_format_returns_401(self, app_client, invalid_format_token):
        resp = app_client.get(
            "/2/users/by/username/testuser",
            headers={"Authorization": f"Bearer {invalid_format_token}"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert "detail" in data

    def test_valid_token_passes_auth_format(self, app_client, valid_token):
        """Valid-format token passes auth gate, fails at upstream (fake token)."""
        resp = app_client.get(
            "/2/users/by/username/testuser",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        # 401 from upstream auth rejection is expected (fake token).
        # But it must NOT be 401 from token format check (AUTH_TOKEN_INVALID_FORMAT).
        assert resp.status_code == 401
        data = resp.json()
        # If format error: {"detail": "..."}
        # If upstream error: {"errors": [{...}]}
        assert "errors" in data, f"Expected structured error, got: {data}"

    def test_bearer_auth_extracts_token(self, app_client, valid_token):
        resp = app_client.get(
            "/2/users/by/username/testuser",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        # Should fail with upstream error (fake token), not format error
        if resp.status_code == 401:
            data = resp.json()
            assert "errors" in data, "Should be upstream error, not format error"


class TestSecurityHeaders:
    def test_security_headers_present(self, app_client):
        resp = app_client.get("/info")
        assert "X-Content-Type-Options" in resp.headers
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in resp.headers
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert "Strict-Transport-Security" in resp.headers

    def test_request_id_in_response(self, app_client):
        resp = app_client.get("/info")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) > 0

    def test_request_id_passthrough(self, app_client):
        resp = app_client.get("/info", headers={"X-Request-ID": "my-custom-id"})
        assert resp.headers["X-Request-ID"] == "my-custom-id"


class TestAdminStats:
    def test_admin_stats_requires_token(self, app_client):
        resp = app_client.get("/admin/stats")
        assert resp.status_code in (404, 401)

    def test_admin_stats_with_wrong_token(self, app_client):
        resp = app_client.get("/admin/stats", headers={"X-Admin-Token": "wrong"})
        assert resp.status_code in (404, 401)


class TestBodySizeLimit:
    def test_body_within_limit_accepted(self, app_client, valid_token):
        resp = app_client.post(
            "/search",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={"q": "test", "type": "Latest"},
        )
        assert resp.status_code != 413

    def test_body_over_limit_rejected(self, app_client, valid_token):
        big = "x" * 2_000_000
        resp = app_client.post(
            "/search",
            headers={"Authorization": f"Bearer {valid_token}"},
            json={"q": big, "type": "Latest"},
        )
        assert resp.status_code == 413
        data = resp.json()
        assert data["errors"][0]["code"] == "VALIDATION_BODY_SIZE"


class TestRawMode:
    def test_raw_query_accepted_by_default(self, app_client, valid_token):
        resp = app_client.get(
            "/2/users/by/username/test?raw=1",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code != 403


class TestSwaggerDocs:
    def test_swagger_docs_accessible(self, app_client):
        resp = app_client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_json_accessible(self, app_client):
        resp = app_client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "paths" in data
