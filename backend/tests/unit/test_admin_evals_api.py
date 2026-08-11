"""Tests for the admin eval endpoints."""

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import require_admin
from api.routers import admin as admin_router
from api.utils import sse_event
from evals.runner import EvalSpecError
from utils.db_storage import DBStorage

EVAL_RUN_BODY = {
    "models": ["openrouter:a"], "jd_ids": ["senior_swe"],
    "custom_jd": None, "data_source": "fixture",
    "judge_model": "google-gla:gemini-2.5-flash-lite", "notes": None,
}

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
    """The response carries the id start_eval minted, not whatever the
    (real or mocked) run_eval returns -- see admin.start_eval's docstring for
    why the run has to happen in the background rather than being awaited
    inline. The mock exists purely to keep this test from spending real money
    on a real model call; its return value is intentionally not asserted.

    The run itself happens on a fire-and-forget `asyncio.create_task`, which
    only gets a chance to execute once something yields control back to the
    event loop. TestClient's portal keeps that loop alive on a background
    thread after `.post()` returns, so a short, bounded poll (real time, not
    `asyncio.sleep`, since this test body isn't itself a coroutine) is enough
    to observe the task calling into the mock -- and it must happen while the
    patch is still active, or a slow scheduler could fall through to the
    *real* run_eval once the context manager restores it.
    """
    mock_run_eval = AsyncMock(return_value="ignored-by-the-endpoint")
    with patch("api.routers.admin.run_eval", mock_run_eval):
        resp = _client().post("/admin/evals", json=EVAL_RUN_BODY)
        assert resp.status_code == 202
        returned_run_id = resp.json()["run_id"]
        uuid.UUID(returned_run_id)  # raises ValueError if it isn't a real uuid

        deadline = time.monotonic() + 2.0
        while not mock_run_eval.await_count and time.monotonic() < deadline:
            time.sleep(0.01)
        assert mock_run_eval.await_count == 1, "background task never called run_eval"

    _, kwargs = mock_run_eval.call_args
    assert kwargs["run_id"] == returned_run_id


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


def test_start_run_requires_auth():
    """Money-spending endpoint: pin auth even with a well-formed body, so a
    422 (bad request shape) can never be mistaken for "auth worked"."""
    app = FastAPI()
    app.include_router(admin_router.router)
    resp = TestClient(app).post("/admin/evals", json=EVAL_RUN_BODY)
    assert resp.status_code == 401


def test_download_requires_auth():
    """Content-exposing endpoint: pin auth independently of the /evals list check."""
    app = FastAPI()
    app.include_router(admin_router.router)
    resp = TestClient(app).get(f"/admin/evals/results/{RESULT['id']}/download?format=word")
    assert resp.status_code == 401


def test_stream_404_when_no_in_flight_run():
    """No mocking needed: an unknown run_id must never match /evals/{run_id}."""
    resp = _client().get(f"/admin/evals/{uuid.uuid4()}/stream")
    assert resp.status_code == 404


def test_stream_yields_cell_then_done():
    """End-to-end through the real StreamingResponse: a queue seeded exactly
    like `start_eval`'s `_on_cell`/`_run` would seed it produces one
    `event: cell` frame per result followed by a single `event: done`."""
    run_id = str(uuid.uuid4())
    queue: "asyncio.Queue[dict]" = asyncio.Queue()
    queue.put_nowait({"id": "cell-1", "status": "success", "composite_score": 0.5})
    queue.put_nowait({"_done": True})
    admin_router._EVAL_STREAMS[run_id] = queue
    try:
        resp = _client().get(f"/admin/evals/{run_id}/stream")
    finally:
        admin_router._EVAL_STREAMS.pop(run_id, None)
    assert resp.status_code == 200
    body = resp.text
    assert "event: cell" in body
    assert '"id": "cell-1"' in body
    assert "event: done" in body
    # cell frame must precede the done frame
    assert body.index("event: cell") < body.index("event: done")


def test_stream_surfaces_error_events():
    """A cell dict carrying `_error` (start_eval's failure path) becomes a
    named `event: error` frame rather than being mistaken for a cell."""
    run_id = str(uuid.uuid4())
    queue: "asyncio.Queue[dict]" = asyncio.Queue()
    queue.put_nowait({"_error": True, "message": "ValueError: boom"})
    queue.put_nowait({"_done": True})
    admin_router._EVAL_STREAMS[run_id] = queue
    try:
        resp = _client().get(f"/admin/evals/{run_id}/stream")
    finally:
        admin_router._EVAL_STREAMS.pop(run_id, None)
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "boom" in resp.text


def test_sse_event_default_frame_has_no_event_line():
    """Existing callers (resume.py's generation streams) pass no `event`."""
    frame = sse_event({"stage": "done"}).decode("utf-8")
    assert frame == 'data: {"stage": "done"}\n\n'
    assert "event:" not in frame


def test_sse_event_named_frame_includes_event_line():
    frame = sse_event({"id": "x"}, event="cell").decode("utf-8")
    assert frame == 'event: cell\ndata: {"id": "x"}\n\n'
