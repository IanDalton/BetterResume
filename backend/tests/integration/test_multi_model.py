"""
Multi-model comparison test.

Run with:
    pytest tests/integration/test_multi_model.py -v --real-ai \\
      --models "google-gla:gemini-2.5-flash-lite,openai:gpt-4o-mini,anthropic:claude-haiku-4-5"

Requires the corresponding API keys:
    GOOGLE_API_KEY / GEMINI_API_KEY   for google-gla
    OPENAI_API_KEY                    for openai
    ANTHROPIC_API_KEY                 for anthropic
"""
import pytest

pytestmark = pytest.mark.timeout(600)

from tests.evaluators.ats_evaluator import ATSEvaluator
from tests.evaluators.llm_judge import LLMJudge
from tests.evaluators.report import ResumeEvaluationReport, print_comparison_table
from tests.evaluators.schema_evaluator import SchemaEvaluator
from tests.fixtures.job_descriptions import JD_SOFTWARE_ENGINEER_SENIOR


class _NoEducationDB:
    def get_job_experiences(self, user_id, type_filter=None):
        return []


@pytest.mark.real_ai
@pytest.mark.slow
async def test_multi_model_comparison(stub_vector_store, models_under_test):
    """
    Generate a resume with each model in --models, score with all evaluators,
    and print a ranked comparison table.

    Hard assertion: every model must produce a schema-valid resume.
    Score values are informational and guide model selection.
    """
    from bot import Bot

    judge = LLMJudge()
    reports = []

    for model_string in models_under_test:
        bot = Bot(
            user_id="test_user_001",
            vector_store=stub_vector_store,
            model=model_string,
            db=_NoEducationDB(),
            auto_ingest=False,
        )

        resume = await bot.generate_resume(JD_SOFTWARE_ENGINEER_SENIOR)

        schema = SchemaEvaluator().evaluate(resume)
        ats = ATSEvaluator().evaluate(resume, JD_SOFTWARE_ENGINEER_SENIOR)
        llm_judge_result = judge.evaluate(resume, JD_SOFTWARE_ENGINEER_SENIOR)

        report = ResumeEvaluationReport(
            model=model_string,
            jd_name="senior_swe",
            schema=schema,
            ats=ats,
            llm_judge=llm_judge_result,
        )
        report.print_summary()
        reports.append(report)

    print_comparison_table(reports)

    failed = [r.model for r in reports if not r.schema.passed]
    assert not failed, f"These models produced schema-invalid resumes: {failed}"
