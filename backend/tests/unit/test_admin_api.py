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

class _FakeAdapters:
    def register_loader(self, *_args, **_kwargs):
        pass


class FakeCursor:
    """Answers fetchone/fetchall based on the last executed SQL."""

    def __init__(self):
        self.executed = []
        self._sql = ""
        self.adapters = _FakeAdapters()

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
        if "job_posting" in self._sql:
            if "LIMIT 3000" in self._sql:
                # Keyword mining selects a single job_posting column.
                return [
                    (b"Senior Python Engineer \xe2\x80",),
                    (b"Python engineer wanted",),
                ]
            # recent_requests preview: user_id, job_posting, created_at.
            # ::bytea preview comes back as raw bytes; include a truncated
            # smart-quote sequence (0xe2 0x80) that is invalid UTF-8.
            return [("u1", b"Senior Engineer \xe2\x80", "2026-06-10")]
        if "SELECT id," in self._sql and "generation_events" in self._sql:
            # get_generation_events export rows
            return [
                (2, "2026-06-12", "u2", "m", "latex", "en", 100, "error", "boom"),
                (1, "2026-06-11", "u1", "m", "word", "en", 200, "success", None),
            ]
        if "status <> 'success'" in self._sql:
            # recent_errors: created_at, user_id, model, format, status, error
            return [("2026-06-12", "u2", "m", "latex", "error", "boom")]
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
    # Invalid UTF-8 bytes (SQL_ASCII DB) must not crash; they decode tolerantly.
    assert stats["recent_requests"] == [
        {
            "user_id": "u1",
            "job_posting_preview": "Senior Engineer �",
            "created_at": "2026-06-10",
        }
    ]
    # New use-case insight fields are always present and well-formed.
    assert len(stats["requests_by_hour"]) == 24
    assert {d["hour"] for d in stats["requests_by_hour"]} == set(range(24))
    assert len(stats["requests_by_weekday"]) == 7
    assert "user_request_distribution" in stats
    assert "by_status" in stats
    assert set(stats["duration_percentiles"]) == {"p50_ms", "p95_ms"}
    # Keyword mining tokenizes, drops stopwords, and counts (UTF-8 tolerant).
    keywords = {k["term"]: k["count"] for k in stats["top_keywords"]}
    assert keywords.get("python") == 2
    assert keywords.get("engineer") == 2
    assert "senior" in keywords


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


def test_get_admin_stats_includes_recent_errors():
    cursor = FakeCursor()
    storage = DBStorage(db_url="postgresql://fake/fake")
    with patch.object(DBStorage, "_get_conn", return_value=_fake_conn(cursor)):
        stats = storage.get_admin_stats(days=30)

    assert stats["recent_errors"] == [
        {
            "created_at": "2026-06-12",
            "user_id": "u2",
            "model": "m",
            "format": "latex",
            "status": "error",
            "error": "boom",
        }
    ]


def test_get_generation_events_returns_all_columns():
    cursor = FakeCursor()
    storage = DBStorage(db_url="postgresql://fake/fake")
    with patch.object(DBStorage, "_get_conn", return_value=_fake_conn(cursor)):
        rows = storage.get_generation_events()

    assert len(rows) == 2
    assert rows[0]["status"] == "error"
    assert rows[0]["error"] == "boom"
    assert rows[1]["status"] == "success"
    assert set(rows[0]) == {
        "id", "created_at", "user_id", "model", "format",
        "language", "duration_ms", "status", "error",
    }


def test_export_logs_returns_csv_for_admin():
    cursor = FakeCursor()
    app = _app()
    app.dependency_overrides[require_admin] = lambda: {"email": "daltioan@gmail.com"}
    client = TestClient(app)

    with patch.object(DBStorage, "_get_conn", return_value=_fake_conn(cursor)):
        resp = client.get("/admin/logs/export")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=generation_logs.csv" in resp.headers["content-disposition"]
    body = resp.text
    assert body.splitlines()[0] == "id,created_at,user_id,model,format,language,duration_ms,status,error"
    assert "boom" in body


def test_export_logs_requires_auth():
    client = TestClient(_app())
    assert client.get("/admin/logs/export").status_code == 401
