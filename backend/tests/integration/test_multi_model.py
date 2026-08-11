"""
Multi-model comparison test.

Run with:
    pytest tests/integration/test_multi_model.py -v --real-ai \\
      --models "google-gla:gemini-2.5-flash-lite,openai:gpt-4o-mini"

Thin wrapper over evals.runner so the CLI and the admin dashboard measure
exactly the same thing.
"""
import os

import pytest

from evals.runner import EvalSpec, run_eval

pytestmark = pytest.mark.timeout(600)


class _CollectingDB:
    def __init__(self):
        self.results = []

    def create_eval_run(self, **kwargs):
        pass

    def insert_eval_result(self, result):
        self.results.append(result)

    def finish_eval_run(self, run_id, status):
        pass


@pytest.mark.real_ai
@pytest.mark.slow
async def test_multi_model_comparison(models_under_test):
    """Generate a resume with each model in --models, score it, print a ranked
    table. Hard assertion: every model must produce a schema-valid resume."""
    db = _CollectingDB()
    spec = EvalSpec(
        models=models_under_test,
        jd_ids=["senior_swe"],
        custom_jd=None,
        data_source="fixture",
        judge_model=os.getenv("JUDGE_MODEL", "google-gla:gemini-2.5-flash-lite"),
        created_by="pytest",
    )
    await run_eval(spec, db=db)

    for r in sorted(db.results, key=lambda x: x["composite_score"] or 0, reverse=True):
        print(f"{r['model']:<48} schema={r['schema_score']} ats={r['ats_score']} "
              f"judge={r['judge_overall']} composite={r['composite_score']} status={r['status']}")

    failed = [r["model"] for r in db.results if not r["schema_passed"]]
    assert not failed, f"These models produced schema-invalid resumes: {failed}"
