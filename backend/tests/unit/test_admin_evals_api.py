"""Tests for the admin eval endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import require_admin
from api.routers import admin as admin_router
from evals.runner import EvalSpecError
from utils.db_storage import DBStorage

RUN = {
    "id": "11111111-1111-1111-1111-111111111111",
    "created_at": "2026-08-10T12:00:00+00:00",
    "finished_at": None,
    "created_by": "daltioan@gmail.com",
    "status": "complete",
    "data_source": "fixture",
    "judge_model": "google-gla:gemini-2.5-flash-lite",
    "models": ["openrouter:a"],
    "jd_ids": ["senior_swe"],
    "custom_jd": None,
    "notes": None,
}

RESULT = {
    "id": "22222222-2222-2222-2222-222222222222",
    "run_id": RUN["id"],
    "model": "openrouter:a",
    "jd_id": "senior_swe",
    "status": "success",
    "composite_score": 0.87,
    "resume_json": {"language": "en"},
}


def _client():
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[require_admin] = lambda: {"email": "daltioan@gmail.com"}
    return TestClient(app)


def test_evals_require_auth():
    app = FastAPI()
    app.include_router(admin_router.router)
    assert TestClient(app).get("/admin/evals").status_code == 401


def test_fixtures_lists_job_descriptions():
    body = _client().get("/admin/evals/fixtures").json()
    ids = [jd["id"] for jd in body["job_descriptions"]]
    assert "senior_swe" in ids
    assert body["default_judge_model"]


def test_start_run_returns_run_id():
    with patch("api.routers.admin.run_eval", AsyncMock(return_value=RUN["id"])):
        resp = _client().post("/admin/evals", json={
            "models": ["openrouter:a"], "jd_ids": ["senior_swe"],
            "custom_jd": None, "data_source": "fixture",
            "judge_model": "google-gla:gemini-2.5-flash-lite", "notes": None,
        })
    assert resp.status_code == 202
    assert resp.json()["run_id"] == RUN["id"]


def test_start_run_400_on_invalid_spec():
    with patch("api.routers.admin.validate_spec", side_effect=EvalSpecError("At most 5 models per run")):
        resp = _client().post("/admin/evals", json={
            "models": ["a:1", "b:2", "c:3", "d:4", "e:5", "f:6"], "jd_ids": ["senior_swe"],
            "custom_jd": None, "data_source": "fixture", "judge_model": None, "notes": None,
        })
    assert resp.status_code == 400
    assert "At most 5 models" in resp.json()["detail"]


def test_list_runs():
    with patch.object(DBStorage, "list_eval_runs", return_value=[RUN]):
        body = _client().get("/admin/evals").json()
    assert body["runs"][0]["id"] == RUN["id"]


def test_get_run_returns_run_and_results():
    with patch.object(DBStorage, "get_eval_run", return_value=RUN), \
         patch.object(DBStorage, "get_eval_results", return_value=[RESULT]):
        body = _client().get(f"/admin/evals/{RUN['id']}").json()
    assert body["run"]["status"] == "complete"
    assert body["results"][0]["composite_score"] == 0.87


def test_get_run_404_when_missing():
    with patch.object(DBStorage, "get_eval_run", return_value=None):
        resp = _client().get(f"/admin/evals/{RUN['id']}")
    assert resp.status_code == 404


def test_compare_returns_per_model_aggregates():
    rows = [{"model": "openrouter:a", "runs": 2, "cells": 4, "avg_composite": 0.81}]
    with patch.object(DBStorage, "get_eval_model_comparison", return_value=rows):
        body = _client().get("/admin/evals/compare").json()
    assert body["models"][0]["avg_composite"] == 0.81


def test_download_404_when_result_missing():
    with patch.object(DBStorage, "get_eval_result", return_value=None):
        resp = _client().get(f"/admin/evals/results/{RESULT['id']}/download?format=word")
    assert resp.status_code == 404


def test_download_400_when_result_has_no_resume():
    with patch.object(DBStorage, "get_eval_result", return_value={**RESULT, "resume_json": None}):
        resp = _client().get(f"/admin/evals/results/{RESULT['id']}/download?format=word")
    assert resp.status_code == 400
