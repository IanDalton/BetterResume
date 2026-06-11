"""Tests for the /admin/stats endpoint and the stats/event DB helpers."""

import contextlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import require_admin
from api.routers import admin as admin_router
from utils.db_storage import DBStorage

SAMPLE_STATS = {
    "totals": {"users": 5, "resume_requests": 12, "generations": 7},
    "generations_per_day": [{"day": "2026-06-10", "count": 3}],
    "by_model": [{"model": "google-gla:gemini-3.1-flash-lite", "count": 7}],
}


def _app():
    app = FastAPI()
    app.include_router(admin_router.router)
    return app


def test_stats_requires_auth():
    client = TestClient(_app())
    assert client.get("/admin/stats").status_code == 401


def test_stats_returns_aggregates_for_admin():
    app = _app()
    app.dependency_overrides[require_admin] = lambda: {"email": "daltioan@gmail.com"}
    client = TestClient(app)

    with patch.object(DBStorage, "get_admin_stats", return_value=SAMPLE_STATS) as mocked:
        resp = client.get("/admin/stats?days=7")

    assert resp.status_code == 200
    assert resp.json() == SAMPLE_STATS
    mocked.assert_called_once_with(days=7)


def test_stats_rejects_invalid_days():
    app = _app()
    app.dependency_overrides[require_admin] = lambda: {"email": "daltioan@gmail.com"}
    client = TestClient(app)
    assert client.get("/admin/stats?days=0").status_code == 422
    assert client.get("/admin/stats?days=9999").status_code == 422


def test_stats_500_on_db_failure():
    app = _app()
    app.dependency_overrides[require_admin] = lambda: {"email": "daltioan@gmail.com"}
    client = TestClient(app)

    with patch.object(DBStorage, "get_admin_stats", side_effect=RuntimeError("db down")):
        resp = client.get("/admin/stats")

    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# DBStorage helpers
# ---------------------------------------------------------------------------

class FakeCursor:
    """Answers fetchone/fetchall based on the last executed SQL."""

    def __init__(self):
        self.executed = []
        self._sql = ""

    def execute(self, sql, params=None):
        self._sql = sql
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        if "FROM users" in self._sql:
            return (5,)
        if "FROM resume_requests" in self._sql:
            return (12, 4)
        if "FROM generation_events" in self._sql:
            return (10, 8, 2500.0)
        return (0,)

    def fetchall(self):
        if "GROUP BY day" in self._sql and "generation_events" in self._sql:
            return [("2026-06-10", 3), ("2026-06-11", 2)]
        if "COALESCE(model" in self._sql:
            return [("google-gla:gemini-3.1-flash-lite", 9), ("openai:gpt-4o-mini", 1)]
        return []


@contextlib.contextmanager
def _fake_conn(cursor):
    conn = MagicMock()
    cursor_cm = MagicMock()
    cursor_cm.__enter__ = MagicMock(return_value=cursor)
    cursor_cm.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor_cm
    yield conn


def test_get_admin_stats_aggregates():
    cursor = FakeCursor()
    storage = DBStorage(db_url="postgresql://fake/fake")
    with patch.object(DBStorage, "_get_conn", return_value=_fake_conn(cursor)):
        stats = storage.get_admin_stats(days=30)

    assert stats["totals"]["users"] == 5
    assert stats["totals"]["resume_requests"] == 12
    assert stats["totals"]["generations"] == 10
    assert stats["totals"]["successful_generations"] == 8
    assert stats["totals"]["success_rate"] == 0.8
    assert stats["totals"]["avg_duration_ms"] == 2500
    assert stats["generations_per_day"] == [
        {"day": "2026-06-10", "count": 3},
        {"day": "2026-06-11", "count": 2},
    ]
    assert stats["by_model"][0]["count"] == 9


def test_record_generation_event_inserts_row():
    cursor = FakeCursor()
    storage = DBStorage(db_url="postgresql://fake/fake")
    with patch.object(DBStorage, "_get_conn", return_value=_fake_conn(cursor)):
        storage.record_generation_event(
            user_id="u1",
            model="google-gla:gemini-3.1-flash-lite",
            format="latex",
            language="en",
            duration_ms=4200,
            status="success",
        )

    sql, params = cursor.executed[-1]
    assert "INSERT INTO generation_events" in sql
    assert params[0] == "u1"
    assert params[4] == 4200
    assert params[5] == "success"


def test_record_generation_event_truncates_error():
    cursor = FakeCursor()
    storage = DBStorage(db_url="postgresql://fake/fake")
    with patch.object(DBStorage, "_get_conn", return_value=_fake_conn(cursor)):
        storage.record_generation_event(user_id="u1", status="error", error="x" * 5000)

    _, params = cursor.executed[-1]
    assert len(params[6]) == 2000
