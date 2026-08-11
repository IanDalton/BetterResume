import asyncio
import csv
import io
import logging
import os
import shutil
import tempfile
import uuid
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from api.auth import require_admin
from api.utils import SSE_HEADERS, _make_writer, sse_event
from evals.fixtures import list_fixtures
from evals.runner import EvalSpec, EvalSpecError, run_eval, validate_spec
from llm.model_config import TASKS, get_model_config, set_task_models
from llm.openrouter_catalog import CatalogUnavailable, fetch_models
from models.resume import ResumeOutputFormat
from utils.db_storage import DBStorage

logger = logging.getLogger("betterresume.api.admin")
router = APIRouter(prefix="/admin", tags=["admin"])

DEFAULT_JUDGE_MODEL = os.getenv("JUDGE_MODEL", "google-gla:gemini-2.5-flash-lite")

# Live cell queues for in-flight runs, keyed by run_id, so /stream can follow a
# run started by POST /evals. Populated by the run's own background task (see
# `start_eval`) via `_on_cell`, and popped by that same task the moment the
# run finishes -- deliberately with no replay grace window, so a run that
# nobody ever streams can't leak a queue of up to MAX_CELLS cell dicts (each
# carrying a full resume_json) forever. A client that connects to /stream
# after the run has already finished gets a 404 and should fall back to
# GET /evals/{run_id} for the completed results.
#
# NOTE: this is process-local, in-memory state. With more than one
# uvicorn/gunicorn worker, a /stream request can land on a worker that never
# saw the POST that started the run, and will 404 even though the run is
# genuinely in flight on a sibling worker. That's inherent to this design,
# not something to work around here -- whatever consumes /stream (e.g. a
# live results grid) needs to know this going in.
_EVAL_STREAMS: Dict[str, "asyncio.Queue[dict]"] = {}

# Strong references to in-flight run tasks. asyncio only holds a weak
# reference to whatever asyncio.create_task() returns, so a bare, otherwise
# unreferenced task can be garbage-collected mid-run. Discarded via the
# task's own done-callback once it finishes.
_RUNNING_EVAL_TASKS: set = set()


@router.get("/stats")
async def admin_stats(days: int = Query(default=30, ge=1, le=365), claims: dict = Depends(require_admin)):
    """Aggregated resume/generation statistics. Admin only."""
    logger.info("Admin stats requested by %s (days=%d)", claims.get("email"), days)
    try:
        stats = DBStorage().get_admin_stats(days=days)
    except Exception:
        logger.exception("Failed to compute admin stats")
        raise HTTPException(status_code=500, detail="Failed to compute statistics")
    return stats


@router.get("/logs/export")
async def export_logs(claims: dict = Depends(require_admin)):
    """Download all generation events as CSV. Admin only."""
    logger.info("Admin logs export requested by %s", claims.get("email"))
    try:
        rows = DBStorage().get_generation_events()
    except Exception:
        logger.exception("Failed to export generation logs")
        raise HTTPException(status_code=500, detail="Failed to export logs")
    buf = io.StringIO()
    fields = ["id", "created_at", "user_id", "model", "requested_model", "fallback_used",
              "format", "language", "duration_ms", "status", "error"]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=generation_logs.csv"},
    )


class ModelConfigUpdate(BaseModel):
    task: Literal["generation", "translation", "import"]
    primary: str
    fallback: Optional[str] = None


def _model_config_payload() -> dict:
    config = get_model_config(force_refresh=True)
    meta = DBStorage().get_app_settings_meta("model.")
    tasks = {}
    for task in TASKS:
        task_models = config.for_task(task)
        row = meta.get(f"model.{task}", {})
        tasks[task] = {
            "primary": task_models.primary,
            "fallback": task_models.fallback,
            "updated_at": row.get("updated_at"),
            "updated_by": row.get("updated_by"),
        }
    return {"tasks": tasks}


@router.get("/models")
async def list_models(tools_only: bool = True, q: str = "", claims: dict = Depends(require_admin)):
    """OpenRouter's model catalog, filtered for the admin picker."""
    try:
        models = await fetch_models()
    except CatalogUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"OpenRouter model list unavailable: {exc}")
    if tools_only:
        models = [m for m in models if m.supports_tools]
    if q:
        needle = q.lower()
        models = [m for m in models if needle in m.id.lower() or needle in m.name.lower()]
    return {"models": [m.as_dict() for m in models]}


@router.get("/model-config")
async def read_model_config(claims: dict = Depends(require_admin)):
    """Current per-task model settings."""
    return _model_config_payload()


@router.put("/model-config")
async def update_model_config(update: ModelConfigUpdate, claims: dict = Depends(require_admin)):
    """Set the primary/fallback models for one task."""
    try:
        set_task_models(update.task, update.primary, update.fallback, updated_by=claims.get("email"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info("Model config for %s changed by %s", update.task, claims.get("email"))
    return _model_config_payload()


class EvalRunRequest(BaseModel):
    models: List[str]
    jd_ids: List[str] = []
    custom_jd: Optional[str] = None
    data_source: str = "fixture"
    judge_model: Optional[str] = DEFAULT_JUDGE_MODEL
    notes: Optional[str] = None


def _eval_download_csv_path() -> str:
    """A minimal, header-only CSV for `_make_writer`.

    Eval resumes are rendered straight from a stored `resume_json` -- there is
    no user CSV behind them. `BaseWriter.__init__` still unconditionally
    `pd.read_csv()`s whatever path it is given (the frame it loads, `self.data`,
    is never actually read by either writer subclass), so `csv_path=None`
    raises a `TypeError` rather than being tolerated. Rather than coupling this
    to the repo's dev-only `jobs.csv` fixture (which may not exist in every
    deployment and carries unrelated personal placeholder data), synthesize an
    empty one on demand.
    """
    fd, path = tempfile.mkstemp(prefix="eval_jobs_", suffix=".csv")
    with os.fdopen(fd, "w", newline="") as fh:
        fh.write("type,company,location,role,start_date,end_date,description\n")
    return path


@router.get("/evals/fixtures")
async def eval_fixtures(claims: dict = Depends(require_admin)):
    """Job-description fixtures available for evaluation runs."""
    return {"job_descriptions": list_fixtures(), "default_judge_model": DEFAULT_JUDGE_MODEL}


@router.post("/evals", status_code=202)
async def start_eval(req: EvalRunRequest, claims: dict = Depends(require_admin)):
    """Start an evaluation run in the background; returns its id immediately.

    The response carries the id minted *here*, not whatever `run_eval`
    eventually returns. A paid, multi-cell run can take minutes (up to
    `MAX_CELLS`=20 cells at `CONCURRENCY`=3 in `evals.runner`, each cell a
    generation call plus a judge call) -- well past most proxy/gateway read
    timeouts (nginx defaults to 60s, Cloudflare cuts at 100s). Awaiting the
    run inline would risk the admin never learning the run_id at all while
    the server keeps paying for the run regardless (uvicorn does not cancel
    a handler on client disconnect), and would make `GET .../stream`
    unreachable by construction, since the id would only be known after the
    last cell finished -- exactly when there is nothing left to stream.
    """
    spec = EvalSpec(
        models=req.models,
        jd_ids=req.jd_ids,
        custom_jd=req.custom_jd,
        data_source=req.data_source,
        judge_model=req.judge_model,
        created_by=claims.get("email") or "admin",
        notes=req.notes,
    )
    try:
        validate_spec(spec)
    except EvalSpecError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Mint the id here so `queue` is registered, and the client can start
    # streaming, before the run itself has done anything.
    run_id = str(uuid.uuid4())
    queue: "asyncio.Queue[dict]" = asyncio.Queue()
    _EVAL_STREAMS[run_id] = queue

    async def _on_cell(result: dict):
        await queue.put(result)

    async def _run():
        try:
            await run_eval(spec, on_cell=_on_cell, run_id=run_id)
        except Exception as exc:
            # This is not a normal empty run: run_eval either never got as
            # far as recording a row, or died mid-run, so GET /evals/{run_id}
            # may 404 with nothing to show for it. Make that distinguishable
            # to anyone still attached to the stream rather than letting the
            # run silently vanish behind an already-returned 202.
            logger.exception("Eval run %s failed", run_id)
            await queue.put({"_error": True, "message": f"{type(exc).__name__}: {exc}"})
        finally:
            await queue.put({"_done": True})
            _EVAL_STREAMS.pop(run_id, None)

    task = asyncio.create_task(_run())
    _RUNNING_EVAL_TASKS.add(task)
    task.add_done_callback(_RUNNING_EVAL_TASKS.discard)

    logger.info("Eval run %s requested by %s: %d model(s)", run_id, claims.get("email"), len(req.models))
    return {"run_id": run_id}


@router.get("/evals")
async def list_evals(limit: int = Query(default=50, ge=1, le=200), claims: dict = Depends(require_admin)):
    """Past evaluation runs, newest first."""
    return {"runs": DBStorage().list_eval_runs(limit=limit)}


@router.get("/evals/compare")
async def compare_evals(claims: dict = Depends(require_admin)):
    """Per-model aggregate across every stored eval result."""
    return {"models": DBStorage().get_eval_model_comparison()}


@router.get("/evals/{run_id}")
async def get_eval(run_id: str, claims: dict = Depends(require_admin)):
    """One run with all of its cells."""
    db = DBStorage()
    run = db.get_eval_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return {"run": run, "results": db.get_eval_results(run_id)}


@router.get("/evals/{run_id}/stream")
async def stream_eval(run_id: str, claims: dict = Depends(require_admin)):
    """SSE stream of cells for an in-flight run."""
    queue = _EVAL_STREAMS.get(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="No in-flight run with that id")

    async def _events():
        try:
            while True:
                item = await queue.get()
                if item.get("_error"):
                    yield sse_event({"message": item.get("message")}, event="error")
                    continue
                if item.get("_done"):
                    yield sse_event({}, event="done")
                    return
                yield sse_event(item, event="cell")
        finally:
            # Idempotent: the run's own background task already pops this on
            # completion (see the `_EVAL_STREAMS` module docstring); this
            # covers a client that disconnects mid-stream instead.
            _EVAL_STREAMS.pop(run_id, None)

    return StreamingResponse(_events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/evals/results/{result_id}/download")
async def download_eval_resume(result_id: str, format: str = "word", claims: dict = Depends(require_admin)):
    """Render a stored eval resume through the production writers."""
    result = DBStorage().get_eval_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Eval result not found")
    if not result.get("resume_json"):
        raise HTTPException(status_code=400, detail="This result has no generated resume")

    resume = ResumeOutputFormat.model_validate(result["resume_json"])
    csv_path = _eval_download_csv_path()
    try:
        writer = _make_writer(format.lower(), csv_path=csv_path, profile_path=None, profile=None)
    finally:
        # BaseWriter.__init__ reads the CSV eagerly (see _eval_download_csv_path's
        # docstring), so it's safe to remove the moment the writer exists.
        os.unlink(csv_path)

    out_dir = tempfile.mkdtemp(prefix="eval_resume_")
    output = os.path.join(out_dir, f"eval_{result_id}{writer.file_ending}")
    try:
        writer.write(resume, output=output, to_pdf=True)
    except Exception:
        logger.exception("Failed rendering eval resume %s", result_id)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Failed to render resume")
    return FileResponse(
        output,
        filename=os.path.basename(output),
        background=BackgroundTask(shutil.rmtree, out_dir, ignore_errors=True),
    )
