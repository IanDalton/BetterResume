"""Shared evaluation runner.

One implementation, two callers: the pytest multi-model integration test and
the admin dashboard's eval endpoint. Each (model, job description) pair is one
cell: generate a resume with that model, score it, persist the row.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from evals.evaluators.ats_evaluator import ATSEvaluator
from evals.evaluators.llm_judge import LLMJudge
from evals.evaluators.report import ResumeEvaluationReport
from evals.evaluators.schema_evaluator import SchemaEvaluator
from evals.fixtures import CUSTOM_JD_ID, JD_FIXTURES, StubVectorStore

logger = logging.getLogger("betterresume.evals.runner")

MAX_MODELS = 5
MAX_CELLS = 20
CONCURRENCY = 3
DATA_SOURCE_FIXTURE = "fixture"


class EvalSpecError(ValueError):
    """The requested evaluation is not runnable."""


class _FixtureDB:
    """No-op DB stand-in used with the `fixture` data source.

    `Bot` hands this to the generation agent's tools (e.g.
    `get_latest_job_experience`); with no explicit `db`, those tools fall back
    to a real `DBStorage()` and attempt a live Postgres connection, which unit
    tests must never require. The fixture user has no real DB row, so an
    empty result is also the semantically correct answer.
    """

    def get_job_experiences(self, user_id: str, type_filter: Optional[str] = None) -> list:
        return []


@dataclass
class EvalSpec:
    models: List[str]
    jd_ids: List[str]
    custom_jd: Optional[str]
    data_source: str
    judge_model: Optional[str]
    created_by: str
    notes: Optional[str] = None

    def jd_entries(self) -> List[Tuple[str, str]]:
        """[(jd_id, jd_text)] for this spec."""
        if self.custom_jd:
            return [(CUSTOM_JD_ID, self.custom_jd)]
        return [(jd_id, JD_FIXTURES[jd_id].text) for jd_id in self.jd_ids]

    def jd_text(self, jd_id: str) -> str:
        """Text for one jd_id — either the custom JD (id `custom`) or a known fixture."""
        if self.custom_jd and jd_id == CUSTOM_JD_ID:
            return self.custom_jd
        return JD_FIXTURES[jd_id].text

    def cells(self) -> List[Tuple[str, str]]:
        """[(model, jd_id)] for this spec."""
        return [(model, jd_id) for model in self.models for jd_id, _ in self.jd_entries()]


def validate_spec(spec: EvalSpec) -> None:
    if not spec.models:
        raise EvalSpecError("Select at least one model")
    if len(spec.models) > MAX_MODELS:
        raise EvalSpecError(f"At most {MAX_MODELS} models per run")
    if spec.custom_jd and spec.jd_ids:
        raise EvalSpecError("Provide either fixture job descriptions or a custom one, not both")
    if not spec.custom_jd and not spec.jd_ids:
        raise EvalSpecError("Select at least one job description")
    unknown = [j for j in spec.jd_ids if j not in JD_FIXTURES]
    if unknown:
        raise EvalSpecError(f"Unknown job description fixture(s): {', '.join(unknown)}")
    if len(spec.cells()) > MAX_CELLS:
        raise EvalSpecError(f"That is {len(spec.cells())} cells; the limit is {MAX_CELLS} per run")
    if spec.data_source != DATA_SOURCE_FIXTURE and not spec.data_source.startswith("user:"):
        raise EvalSpecError("data_source must be 'fixture' or 'user:<user_id>'")


def _model_for(model_string: str):
    """Indirection so tests can substitute TestModel without touching the runner."""
    return model_string


def _judge_for(model_string: Optional[str]):
    """Indirection so tests can substitute the judge model."""
    return model_string


def _vector_store_for(spec: EvalSpec):
    """(vector_store, user_id, db) for the spec's data source.

    `db` is handed straight through to `Bot`. For the fixture source it is a
    no-op stand-in (see `_FixtureDB`); for a real user it is left `None` so
    `Bot`/the agent tools fall back to real `DBStorage`, which is exactly what
    an eval against that user's live data should read.
    """
    if spec.data_source == DATA_SOURCE_FIXTURE:
        return StubVectorStore(user_id="eval_fixture_user"), "eval_fixture_user", _FixtureDB()
    user_id = spec.data_source.split(":", 1)[1]
    from llm.vector_store import PGVectorStore

    return PGVectorStore(user_id=user_id), user_id, None


async def _run_cell(spec: EvalSpec, model_string: str, jd_id: str, jd_text: str, run_id: str) -> dict:
    """Generate + score one (model, JD) pair. Never raises; failures are recorded."""
    from bot import Bot

    result: dict = {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "model": model_string,
        "jd_id": jd_id,
        "status": "error",
        "error": None,
        "duration_ms": None,
        "input_tokens": None,
        "output_tokens": None,
        "fallback_used": False,
        "schema_score": None, "schema_passed": None, "schema_errors": None,
        "ats_score": None, "ats_coverage": None, "missing_keywords": None,
        "judge_overall": None, "judge_relevance": None, "judge_quality": None,
        "judge_coherence": None, "judge_reasoning": None,
        "composite_score": None, "resume_json": None,
    }
    start = time.monotonic()
    try:
        store, user_id, db_for_bot = _vector_store_for(spec)
        bot = Bot(
            user_id=user_id,
            vector_store=store,
            model=_model_for(model_string),
            db=db_for_bot,
            auto_ingest=False,
        )
        resume = await bot.generate_resume(jd_text)
        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        result["fallback_used"] = bool(bot.last_fallback_used)
        result["input_tokens"] = bot.last_input_tokens
        result["output_tokens"] = bot.last_output_tokens
        result["resume_json"] = resume.model_dump()

        schema = SchemaEvaluator().evaluate(resume)
        result.update(
            schema_score=schema.score,
            schema_passed=schema.passed,
            schema_errors=list(schema.errors or []),
        )

        ats = ATSEvaluator().evaluate(resume, jd_text)
        result.update(
            ats_score=ats.score,
            ats_coverage=ats.keyword_coverage,
            missing_keywords=list(ats.missing_keywords or [])[:20],
        )

        judge_result = None
        if spec.judge_model:
            judge_result = await LLMJudge(judge_model=_judge_for(spec.judge_model)).aevaluate(resume, jd_text)
            result.update(
                judge_overall=judge_result.overall_score,
                judge_relevance=judge_result.relevance_score,
                judge_quality=judge_result.quality_score,
                judge_coherence=judge_result.coherence_score,
                judge_reasoning=judge_result.reasoning,
            )

        # Reuse ResumeEvaluationReport's weighting rather than re-implementing it here,
        # so a dashboard run and the pytest/report path can never silently diverge.
        report = ResumeEvaluationReport(
            model=model_string, jd_name=jd_id, schema=schema, ats=ats, llm_judge=judge_result,
        )
        result["composite_score"] = report.composite_score
        result["status"] = "success"
    except Exception as exc:
        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        result["error"] = f"{type(exc).__name__}: {exc}"[:2000]
        logger.warning("Eval cell failed model=%s jd=%s: %s", model_string, jd_id, exc)
    return result


async def run_eval(
    spec: EvalSpec,
    *,
    db: Any = None,
    on_cell: Optional[Callable[[dict], Awaitable[None]]] = None,
    run_id: Optional[str] = None,
) -> str:
    """Execute an evaluation run, persisting each cell as it completes.

    Returns the run id. Callers that need the id before the run starts (the API,
    so it can hand the client a stream to follow) pass one in. Cell failures are
    recorded, not raised.
    """
    validate_spec(spec)
    if db is None:
        from utils.db_storage import DBStorage
        db = DBStorage()

    run_id = run_id or str(uuid.uuid4())
    # `db` methods are synchronous (real DBStorage does blocking psycopg I/O); this
    # runner is also invoked from inside FastAPI's event loop (the admin endpoint), so
    # every call must go through a thread rather than block the loop for every other
    # in-flight request.
    await asyncio.to_thread(
        db.create_eval_run,
        run_id=run_id,
        created_by=spec.created_by,
        data_source=spec.data_source,
        judge_model=spec.judge_model,
        models=list(spec.models),
        jd_ids=[jd_id for jd_id, _ in spec.jd_entries()],
        custom_jd=spec.custom_jd,
        notes=spec.notes,
    )
    logger.info("Eval run %s started by %s: %d cells", run_id, spec.created_by, len(spec.cells()))

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _guarded(model_string: str, jd_id: str, jd_text: str):
        async with semaphore:
            result = await _run_cell(spec, model_string, jd_id, jd_text, run_id)
        # Bookkeeping failures (a dropped connection, a disconnected SSE client) must
        # degrade to a logged warning for this cell, not tear down the whole run: by
        # this point the (paid) generation already happened, and sibling cells are
        # already running as their own gather()-owned tasks that nothing here should
        # abort mid-flight.
        try:
            await asyncio.to_thread(db.insert_eval_result, result)
        except Exception:
            logger.exception(
                "Eval run %s: failed to persist result for model=%s jd=%s",
                run_id, model_string, jd_id,
            )
        if on_cell:
            try:
                await on_cell(result)
            except Exception:
                logger.exception(
                    "Eval run %s: on_cell callback failed for model=%s jd=%s",
                    run_id, model_string, jd_id,
                )
        return result

    tasks = [
        _guarded(model_string, jd_id, jd_text)
        for model_string in spec.models
        for jd_id, jd_text in spec.jd_entries()
    ]
    try:
        await asyncio.gather(*tasks)
        await asyncio.to_thread(db.finish_eval_run, run_id, "complete")
    except Exception:
        logger.exception("Eval run %s failed", run_id)
        await asyncio.to_thread(db.finish_eval_run, run_id, "failed")
        raise
    logger.info("Eval run %s complete", run_id)
    return run_id
