"""Shared fixtures for Xapi test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure the project root is on sys.path so app.* imports work
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def app_client():
    """Return a FastAPI TestClient for the full app.

    Session-scoped so all tests share one app instance.
    """
    # Disable caching + rate limiting for tests
    os.environ.setdefault("RESPONSE_CACHE_TTL", "0")
    os.environ.setdefault("RATE_LIMIT_PER_TOKEN", "9999")
    os.environ.setdefault("ALLOW_QUERY_AUTH", "1")
    os.environ.setdefault("ENABLE_RAW", "1")

    from main import app
    with TestClient(app) as client:
        yield client


@pytest.fixture
def valid_token() -> str:
    """A syntactically valid-looking auth_token (40 hex chars)."""
    return "a" * 40


@pytest.fixture
def invalid_format_token() -> str:
    """An invalid-format auth_token."""
    return "not-valid-token"
