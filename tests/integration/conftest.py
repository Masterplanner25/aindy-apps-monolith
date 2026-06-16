"""
Integration test conftest.

Requires a live Postgres + Redis + Mongo stack:
    docker compose -f docker-compose.test.yml up -d
    pytest -c pytest.integration.ini -v

The root conftest.py (tests/conftest.py) and shared fixtures
(tests/fixtures/db.py, tests/fixtures/client.py) are loaded automatically
by pytest. This file adds integration-specific guards and any additional
fixtures needed only in tests/integration/.
"""
from __future__ import annotations

import os
import pytest


def pytest_collection_modifyitems(config, items):
    """Skip integration tests when DATABASE_URL is not a live PostgreSQL URL."""
    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith("postgresql"):
        return
    skip = pytest.mark.skip(
        reason="Integration tests require a live PostgreSQL database. "
        "Run: docker compose -f docker-compose.test.yml up -d, "
        "then: pytest -c pytest.integration.ini -v"
    )
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)
