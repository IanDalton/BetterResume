"""`resume_analyses` persistence and the admin aggregates built on it."""

import contextlib
from unittest.mock import patch

from utils.db_storage import DBStorage, _EMPTY_ANALYSES_STATS
from tests.unit.test_app_settings_db import FakeConn, FakeCursor


def _patch_conn(cursor):
    @contextlib.contextmanager
    def fake_get_conn(self):
        yield FakeConn(cursor)

    return patch.object(DBStorage, "_get_conn", fake_get_conn)


def test_schema_creates_the_analyses_table():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().init_schema()
    assert any("CREATE TABLE IF NOT EXISTS resume_analyses" in sql for sql, _ in cur.executed)


def test_record_resume_analysis_persists_every_score():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().record_resume_analysis(
            user_id="u1", source="imported", generation_model=None, review_model="openrouter:j",
            ats_score=70, keyword_coverage=60, review_overall=77, review_relevance=80,
            review_quality=60, review_coherence=90, review_error=None, duration_ms=1500,
        )
    sql, params = cur.executed[0]
    assert "INSERT INTO resume_analyses" in sql
    assert params == ("u1", "imported", None, "openrouter:j", 70, 60, 77, 80, 60, 90, None, 1500)


def test_latest_generation_model_reads_the_most_recent_success():
    cur = FakeCursor(rows=[("openrouter:gen",)])
    with _patch_conn(cur):
        model = DBStorage().get_latest_generation_model("u1")
    assert model == "openrouter:gen"
    sql, params = cur.executed[0]
    assert "status = 'success'" in sql and "ORDER BY created_at DESC LIMIT 1" in sql
    assert params == ("u1",)


def test_latest_generation_model_is_none_without_generations():
    with _patch_conn(FakeCursor(rows=[])):
        assert DBStorage().get_latest_generation_model("u1") is None


class _StatsCursor(FakeCursor):
    def fetchone(self):
        return (12, 71.4, 66.6, 9, 3)

    def fetchall(self):
        return [("openrouter:gen-a", 8, 74.2, 70.0), ("(imported)", 3, 55.5, None)]


def test_analysis_stats_aggregates_and_breaks_down_by_generation_model():
    cur = _StatsCursor()
    stats = DBStorage._analysis_stats(cur, 30)
    assert stats == {
        "count": 12, "avg_ats": 71, "avg_review": 67, "reviewed": 9, "imported": 3,
        "by_generation_model": [
            {"model": "openrouter:gen-a", "count": 8, "avg_ats": 74, "avg_review": 70},
            {"model": "(imported)", "count": 3, "avg_ats": 56, "avg_review": None},
        ],
    }
    assert all(params == (30,) for _, params in cur.executed)


def test_analysis_stats_tolerate_an_empty_table():
    stats = DBStorage._analysis_stats(FakeCursor(rows=[]), 7)
    assert stats == _EMPTY_ANALYSES_STATS
