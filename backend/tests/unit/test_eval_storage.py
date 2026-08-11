"""Tests for eval run/result persistence."""

import contextlib
from unittest.mock import patch

from utils.db_storage import DBStorage
from tests.unit.test_app_settings_db import FakeConn, FakeCursor


def _patch_conn(cursor):
    @contextlib.contextmanager
    def fake_get_conn(self):
        yield FakeConn(cursor)

    return patch.object(DBStorage, "_get_conn", fake_get_conn)


def test_create_eval_run_inserts_running_status():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().create_eval_run(
            run_id="11111111-1111-1111-1111-111111111111",
            created_by="admin@example.com",
            data_source="fixture",
            judge_model="google-gla:gemini-2.5-flash-lite",
            models=["openrouter:a", "openrouter:b"],
            jd_ids=["senior_swe"],
            custom_jd=None,
            notes=None,
        )
    sql, params = cur.executed[0]
    assert "INSERT INTO eval_runs" in sql
    assert "running" in params


def test_finish_eval_run_sets_status_and_timestamp():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().finish_eval_run("11111111-1111-1111-1111-111111111111", "complete")
    sql, params = cur.executed[0]
    assert "UPDATE eval_runs" in sql and "finished_at = NOW()" in sql
    assert params[0] == "complete"


def test_insert_eval_result_persists_resume_json():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().insert_eval_result({
            "id": "22222222-2222-2222-2222-222222222222",
            "run_id": "11111111-1111-1111-1111-111111111111",
            "model": "openrouter:a",
            "jd_id": "senior_swe",
            "status": "success",
            "error": None,
            "duration_ms": 4200,
            "input_tokens": 900,
            "output_tokens": 700,
            "fallback_used": False,
            "schema_score": 1.0,
            "schema_passed": True,
            "schema_errors": [],
            "ats_score": 0.8,
            "ats_coverage": 0.75,
            "missing_keywords": ["airflow"],
            "judge_overall": 0.82,
            "judge_relevance": 0.8,
            "judge_quality": 0.8,
            "judge_coherence": 0.9,
            "judge_reasoning": "Good.",
            "composite_score": 0.87,
            "resume_json": {"language": "en"},
            "unforced_tool_choice": True,
            "allow_reasoning": False,
        })
    sql, params = cur.executed[0]
    assert "INSERT INTO eval_results" in sql
    assert "resume_json" in sql
    assert "unforced_tool_choice" in sql and "allow_reasoning" in sql
    columns = [c.strip() for c in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
    assert params[columns.index("unforced_tool_choice")] is True


def test_comparison_reports_whether_a_model_ever_needed_a_concession():
    """`BOOL_OR` across the model's cells: one run that had to concede is
    enough to qualify the aggregate score."""
    cur = FakeCursor(rows=[(
        "openrouter:a", 2, 6, 1.0, 0.87, 1.0, 0.8, 0.82, 4200, False, True, None,
    )])
    with _patch_conn(cur):
        rows = DBStorage().get_eval_model_comparison()
    assert rows[0]["model"] == "openrouter:a"
    assert rows[0]["unforced_tool_choice"] is False
    assert rows[0]["allow_reasoning"] is True


def test_get_eval_results_builds_dicts():
    cur = FakeCursor(rows=[(
        "22222222-2222-2222-2222-222222222222", "11111111-1111-1111-1111-111111111111",
        "openrouter:a", "senior_swe", "success", None, 4200, 900, 700, False,
        1.0, True, [], 0.8, 0.75, ["airflow"], 0.82, 0.8, 0.8, 0.9, "Good.", None, 0.87,
        {"language": "en"}, True, False, None,
    )])
    with _patch_conn(cur):
        results = DBStorage().get_eval_results("11111111-1111-1111-1111-111111111111")
    assert results[0]["model"] == "openrouter:a"
    assert results[0]["resume_json"] == {"language": "en"}
    assert results[0]["composite_score"] == 0.87
    # Routing concessions travel with the row, so the dashboard can qualify
    # the scores next to them.
    assert results[0]["unforced_tool_choice"] is True
    assert results[0]["allow_reasoning"] is False


def test_mark_running_evals_interrupted_returns_rowcount():
    cur = FakeCursor(rowcount=3)
    with _patch_conn(cur):
        result = DBStorage().mark_running_evals_interrupted()
    sql, _ = cur.executed[0]
    assert "UPDATE eval_runs" in sql and "interrupted" in sql
    assert result == 3


def test_mark_running_evals_interrupted_treats_undefined_rowcount_as_zero():
    """psycopg leaves rowcount at -1 ('undefined') for some statements; that
    must never surface as a nonsense negative count in startup logs."""
    cur = FakeCursor(rowcount=-1)
    with _patch_conn(cur):
        result = DBStorage().mark_running_evals_interrupted()
    assert result == 0
