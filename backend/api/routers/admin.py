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
from llm.model_config import TASKS, TASKS_WITH_FALLBACK, get_model_config, set_task_models
from llm.model_names import validate_model_string
from llm.model_probe import probe_model
from llm.openrouter_catalog import CatalogUnavailable, fetch_models
from models.resume import ResumeOutputFormat
from utils.db_storage import DBStorage

logger = logging.getLogger("betterresume.api.admin")
router = APIRouter(prefix="/admin", tags=["admin"])


def _configured_judge_model() -> str:
    """The judge model currently set for the `judge` task in the dashboard.

    Read per request rather than captured at import: the admin can change it at
    any time, and the config layer already TTL-caches the lookup.
    """
    return get_model_config().for_task("judge").primary


class _EvalStream:
    """Fan-out for one run's live cells to every concurrent /stream request.

    A single run can have zero or more subscribers at any moment (no tab
    open, one tab, a second tab, a reconnect racing a drop, ...); each must
    see every cell and the single terminal signal, not split the cells or
    race for the one `_done`/`_error` sentinel a plain `asyncio.Queue` would
    have delivered to only one of them.
    """

    def __init__(self) -> None:
        self._subscribers: "set[asyncio.Queue[dict]]" = set()

    def subscribe(self) -> "asyncio.Queue[dict]":
        queue: "asyncio.Queue[dict]" = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[dict]") -> None:
        self._subscribers.discard(queue)

    async def publish(self, item: dict) -> None:
        # Snapshot: `publish` and `unsubscribe` can interleave across awaits,
        # and mutating a set while iterating it raises.
        for queue in list(self._subscribers):
            await queue.put(item)


# Live cell streams for in-flight runs, keyed by run_id, so /stream can follow
# a run started by POST /evals. Populated by the run's own background task
# (see `start_eval`) via `_on_cell`, and popped by that same task the moment
# the run finishes -- deliberately with no replay grace window, so a run that
# nobody ever streams can't leak state (each cell dict carries a full
# resume_json) forever. A client that connects to /stream after the run has
# already finished gets a 404 and should fall back to GET /evals/{run_id} for
# the completed results. A subscriber disconnecting mid-run only removes
# itself (see `stream_eval`) -- the run's entry, and every other subscriber,
# are untouched.
#
# NOTE: this is process-local, in-memory state. With more than one
# uvicorn/gunicorn worker, a /stream request can land on a worker that never
# saw the POST that started the run, and will 404 even though the run is
# genuinely in flight on a sibling worker. That's inherent to this design,
# not something to work around here -- whatever consumes /stream (e.g. a
# live results grid) needs to know this going in.
_EVAL_STREAMS: Dict[str, _EvalStream] = {}

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
    task: Literal["generation", "translation", "import", "judge"]
    primary: str
    fallback: Optional[str] = None
    # Set to skip the live compatibility probe -- for saving a model the probe
    # rejected anyway (e.g. the provider is briefly down, or you know better).
    skip_check: bool = False


class ModelCheckRequest(BaseModel):
    models: List[str]


MAX_MODEL_CHECKS = 10


def _check_payload(model: str, result) -> dict:
    return {
        "model": model, "ok": result.ok, "detail": result.detail,
        "forced_tool_choice": result.forced_tool_choice,
        "reasoning_disabled": not result.concessions.allow_reasoning,
        "message": result.message,
    }


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
            "supports_fallback": task in TASKS_WITH_FALLBACK,
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


@router.post("/model-check")
async def check_model(req: ModelCheckRequest, claims: dict = Depends(require_admin)):
    """Ask each model to serve one minimal request in our exact shape.

    Cheap (a few tokens each) and the only reliable way to learn what a model
    can actually do: the catalog's `supported_parameters` claims support that
    individual endpoints don't honour. Used by the eval pre-flight (so a broken
    model does not eat a paid run) and the model picker's Test action.
    """
    models = list(dict.fromkeys(m for m in req.models if m.strip()))
    if not models:
        raise HTTPException(status_code=400, detail="No models to check")
    if len(models) > MAX_MODEL_CHECKS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_MODEL_CHECKS} models per check")
    # Concurrent: an eval pre-flight checks every selected model, and the admin
    # is waiting on the slowest one either way.
    results = await asyncio.gather(*(probe_model(m) for m in models))
    for model, result in zip(models, results):
        logger.info("Model check for %s by %s: ok=%s concessions=%s",
                    model, claims.get("email"), result.ok, result.concessions.describe() or "none")
    return {"results": [_check_payload(m, r) for m, r in zip(models, results)]}


@router.put("/model-config")
async def update_model_config(update: ModelConfigUpdate, claims: dict = Depends(require_admin)):
    """Set the primary/fallback models for one task.

    The model is probed before it is stored: a model that cannot serve our
    request shape would otherwise be accepted here and only fail later, on a
    real user's generation, as an opaque provider error.
    """
    # Cheap checks (shape, known provider) before the paid one, so a typo comes
    # back as a typo rather than as a failed request to a nonexistent model.
    try:
        for model in filter(None, (update.primary, update.fallback)):
            validate_model_string(model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    notices = []
    if not update.skip_check:
        # The fallback is checked too: `FallbackModel` resolves both sub-models
        # up front, so a broken fallback breaks runs whose primary is healthy.
        for model in filter(None, (update.primary, update.fallback)):
            result = await probe_model(model)
            if not result.ok:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{model} failed a live check and was not saved: {result.message}. "
                        "Pick another model, or re-save with skip_check to store it anyway."
                    ),
                )
            if result.concessions:
                # Usable, but worth saying out loud: each concession costs
                # something (retries on weaker models, or reasoning tokens).
                notices.append(f"{model}: {result.message}")
    try:
        set_task_models(update.task, update.primary, update.fallback, updated_by=claims.get("email"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info("Model config for %s changed by %s", update.task, claims.get("email"))
    return {**_model_config_payload(), "notice": "; ".join(notices) or None}


class EvalRunRequest(BaseModel):
    models: List[str]
    jd_ids: List[str] = []
    custom_jd: Optional[str] = None
    data_source: str = "fixture"
    # `None` means "use the dashboard's configured judge model"; an explicit
    # empty string is how the UI asks for a run with no judge at all.
    judge_model: Optional[str] = None
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
    return {"job_descriptions": list_fixtures(), "default_judge_model": _configured_judge_model()}


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
        judge_model=_configured_judge_model() if req.judge_model is None else (req.judge_model or None),
        created_by=claims.get("email") or "admin",
        notes=req.notes,
    )
    try:
        validate_spec(spec)
    except EvalSpecError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Mint the id here so `stream` is registered, and the client can start
    # streaming, before the run itself has done anything.
    run_id = str(uuid.uuid4())
    stream = _EvalStream()
    _EVAL_STREAMS[run_id] = stream

    async def _on_cell(result: dict):
        await stream.publish(result)

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
            await stream.publish({"_error": True, "message": f"{type(exc).__name__}: {exc}"})
        finally:
            await stream.publish({"_done": True})
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
    """SSE stream of cells for an in-flight run.

    Multiple concurrent requests for the same run_id (two tabs, or a
    reconnect racing a drop) each get their own subscription via
    `_EvalStream.subscribe`, so every one of them sees every cell and the
    terminal `done`/`error` frame -- not a fan-in split across whichever
    consumer happened to call `queue.get()` first.
    """
    stream = _EVAL_STREAMS.get(run_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="No in-flight run with that id")
    queue = stream.subscribe()

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
            # Only this subscriber goes away. The run's entry in
            # `_EVAL_STREAMS` (and any sibling subscriber) is untouched --
            # the run's own background task is solely responsible for
            # popping it, once the run itself finishes (see the
            # `_EVAL_STREAMS` module docstring).
            stream.unsubscribe(queue)

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
        # `to_pdf=False`: the PDF conversion's *return value* was never used
        # below anyway -- FileResponse always serves `output` (the pre-conversion
        # .docx/.tex path), not whatever path/handle `write()` returns. Asking
        # for a PDF here only bought wasted soffice/pdflatex work on every
        # download, plus an extra failure mode: a pdflatex hiccup raises
        # RuntimeError (see LatexResumeWriter.to_pdf) and turns into a 500 here
        # even though a perfectly valid .tex had already been written to disk.
        writer.write(resume, output=output, to_pdf=False)
    except Exception:
        logger.exception("Failed rendering eval resume %s", result_id)
        shutil.rmtree(out_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Failed to render resume")
    return FileResponse(
        output,
        filename=os.path.basename(output),
        background=BackgroundTask(shutil.rmtree, out_dir, ignore_errors=True),
    )
