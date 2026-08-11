"""Tests for the shared eval runner. No real models, no real database."""

from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel

from evals import runner
from evals.runner import EvalSpec, EvalSpecError


class RecordingDB:
    """Captures what the runner would persist."""

    def __init__(self):
        self.runs = []
        self.results = []
        self.finished = []

    def create_eval_run(self, **kwargs):
        self.runs.append(kwargs)

    def insert_eval_result(self, result):
        self.results.append(result)

    def finish_eval_run(self, run_id, status):
        self.finished.append((run_id, status))


def _spec(**overrides):
    base = dict(
        models=["test:a", "test:b"],
        jd_ids=["senior_swe"],
        custom_jd=None,
        data_source="fixture",
        judge_model="test:judge",
        created_by="admin@example.com",
    )
    base.update(overrides)
    return EvalSpec(**base)


# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------

def test_rejects_empty_models():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(models=[]))


def test_rejects_too_many_models():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(models=[f"test:{i}" for i in range(runner.MAX_MODELS + 1)]))


def test_rejects_unknown_fixture_id():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(jd_ids=["not_a_fixture"]))


def test_rejects_both_fixtures_and_custom_jd():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(jd_ids=["senior_swe"], custom_jd="Some pasted JD"))


def test_rejects_no_job_description_at_all():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(jd_ids=[], custom_jd=None))


def test_accepts_custom_jd_alone():
    runner.validate_spec(_spec(jd_ids=[], custom_jd="Senior Python engineer wanted"))


def test_cells_are_model_x_jd():
    spec = _spec(models=["test:a", "test:b"], jd_ids=["senior_swe", "junior_analyst"])
    assert len(spec.cells()) == 4


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

async def test_run_persists_one_result_per_cell(sample_resume_output):
    db = RecordingDB()
    seen = []

    async def on_cell(result):
        seen.append(result)

    with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
            custom_output_args=sample_resume_output.model_dump())), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        run_id = await runner.run_eval(_spec(models=["test:a", "test:b"]), db=db, on_cell=on_cell)

    assert len(db.results) == 2
    assert len(seen) == 2
    assert db.finished == [(run_id, "complete")]
    assert all(r["status"] == "success" for r in db.results)
    assert db.results[0]["resume_json"]["language"] == "en"
    assert db.results[0]["composite_score"] is not None


async def test_successful_cell_records_token_usage(sample_resume_output):
    """A successful cell's persisted result must carry real token counts, not
    the `None` placeholders the result dict is seeded with -- before this fix
    the Tokens column in the eval dashboard could never populate."""
    db = RecordingDB()

    with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
            custom_output_args=sample_resume_output.model_dump())), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        await runner.run_eval(_spec(models=["test:a"]), db=db)

    result = db.results[0]
    assert result["status"] == "success"
    assert result["input_tokens"] is not None and result["input_tokens"] > 0
    assert result["output_tokens"] is not None and result["output_tokens"] > 0


async def test_failing_cell_is_recorded_and_does_not_abort_run(sample_resume_output):
    db = RecordingDB()

    def model_for(name):
        if name == "test:bad":
            raise RuntimeError("provider exploded")
        return TestModel(custom_output_args=sample_resume_output.model_dump())

    with patch.object(runner, "_model_for", side_effect=model_for), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        run_id = await runner.run_eval(_spec(models=["test:bad", "test:good"]), db=db)

    by_model = {r["model"]: r for r in db.results}
    assert by_model["test:bad"]["status"] == "error"
    assert "provider exploded" in by_model["test:bad"]["error"]
    assert by_model["test:good"]["status"] == "success"
    assert db.finished == [(run_id, "complete")]


async def test_cell_cap_is_enforced():
    spec = _spec(models=[f"test:{i}" for i in range(5)], jd_ids=["senior_swe", "junior_analyst", "product_manager"])
    with patch.object(runner, "MAX_CELLS", 10):
        with pytest.raises(EvalSpecError, match="cells"):
            runner.validate_spec(spec)


async def test_custom_jd_is_used_and_labelled(sample_resume_output):
    db = RecordingDB()
    with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
            custom_output_args=sample_resume_output.model_dump())), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        await runner.run_eval(_spec(models=["test:a"], jd_ids=[], custom_jd="Pasted JD text"), db=db)

    assert db.results[0]["jd_id"] == "custom"
    assert db.runs[0]["custom_jd"] == "Pasted JD text"


async def test_insert_failure_for_one_cell_does_not_abort_the_run(sample_resume_output):
    """A raising `insert_eval_result` (e.g. a dropped connection) must degrade to a
    logged warning for that cell only — sibling cells still complete and persist, and
    the run still finishes `complete` rather than being torn down mid-flight."""

    class FlakyDB(RecordingDB):
        def insert_eval_result(self, result):
            if result["model"] == "test:bad":
                raise RuntimeError("db write failed")
            super().insert_eval_result(result)

    db = FlakyDB()
    seen = []

    async def on_cell(result):
        seen.append(result)

    with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
            custom_output_args=sample_resume_output.model_dump())), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        run_id = await runner.run_eval(_spec(models=["test:bad", "test:good"]), db=db, on_cell=on_cell)

    # test:bad's result failed to persist; test:good's still made it through.
    assert [r["model"] for r in db.results] == ["test:good"]
    # on_cell still saw both cells, even the one whose persistence failed.
    assert {r["model"] for r in seen} == {"test:bad", "test:good"}
    assert db.finished == [(run_id, "complete")]


async def test_finish_complete_failure_does_not_misreport_run_as_failed(sample_resume_output):
    """If `finish_eval_run(run_id, "complete")` raises (e.g. a transient DB
    error) after every cell already succeeded and persisted, the run must not
    be reported as failed -- that would call `finish_eval_run(..., "failed")`,
    which would raise the same way, and would tell the admin a fully-successful
    run failed. `run_eval` itself must not raise either."""

    class FlakyFinishDB(RecordingDB):
        def finish_eval_run(self, run_id, status):
            if status == "complete":
                raise RuntimeError("db write failed")
            super().finish_eval_run(run_id, status)

    db = FlakyFinishDB()

    with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
            custom_output_args=sample_resume_output.model_dump())), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        run_id = await runner.run_eval(_spec(models=["test:a"]), db=db)

    # The cell's result is persisted regardless of the bookkeeping failure.
    assert len(db.results) == 1
    assert db.results[0]["status"] == "success"
    # The failed "complete" write must not be followed by a "failed" write.
    assert db.finished == []


async def test_on_cell_failure_for_one_cell_does_not_abort_the_run(sample_resume_output):
    """An `on_cell` callback that raises (e.g. pushing to a queue for a client that
    disconnected) must not prevent other cells from completing and persisting."""
    db = RecordingDB()

    async def on_cell(result):
        if result["model"] == "test:bad":
            raise RuntimeError("client disconnected")

    with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
            custom_output_args=sample_resume_output.model_dump())), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        run_id = await runner.run_eval(_spec(models=["test:bad", "test:good"]), db=db, on_cell=on_cell)

    # Both cells still persisted despite one on_cell callback raising.
    assert {r["model"] for r in db.results} == {"test:bad", "test:good"}
    assert db.finished == [(run_id, "complete")]


# ---------------------------------------------------------------------------
# Routing concessions (see llm/model_routing.py)
#
# A score means something different when the model had to be given a
# concession to produce it, so each cell records what its model needed.
# ---------------------------------------------------------------------------

async def test_cell_records_the_concessions_its_model_needed(sample_resume_output):
    from llm import model_routing

    db = RecordingDB()
    model_routing.reset_known_models()
    model_routing.remember("openrouter:needs/help", unforced_tool_choice=True, allow_reasoning=True)
    try:
        with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
                custom_output_args=sample_resume_output.model_dump())), \
             patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
                custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
            await runner.run_eval(_spec(models=["openrouter:needs/help"]), db=db)
    finally:
        model_routing.reset_known_models()

    result = db.results[0]
    assert result["status"] == "success"
    assert result["unforced_tool_choice"] is True
    assert result["allow_reasoning"] is True


async def test_cell_records_no_concessions_for_a_model_that_needed_none(sample_resume_output):
    from llm import model_routing

    db = RecordingDB()
    model_routing.reset_known_models()
    with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
            custom_output_args=sample_resume_output.model_dump())), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        await runner.run_eval(_spec(models=["openrouter:clean/model"]), db=db)

    assert db.results[0]["unforced_tool_choice"] is False
    assert db.results[0]["allow_reasoning"] is False


async def test_a_failed_cell_still_records_its_concessions():
    """A cell that failed *after* conceding is a different story from one that
    failed outright, so the flags are recorded on the error path too."""
    from llm import model_routing

    db = RecordingDB()
    model_routing.reset_known_models()
    model_routing.remember("openrouter:needs/help", allow_reasoning=True)
    try:
        def _boom(name):
            raise RuntimeError("provider exploded")

        with patch.object(runner, "_model_for", side_effect=_boom):
            await runner.run_eval(_spec(models=["openrouter:needs/help"]), db=db)
    finally:
        model_routing.reset_known_models()

    result = db.results[0]
    assert result["status"] == "error"
    assert result["allow_reasoning"] is True
