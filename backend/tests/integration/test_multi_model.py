"""
Multi-model comparison test.

Run with:
    pytest tests/integration/test_multi_model.py -v --real-ai \\
      --models "google_genai:gemini-2.5-flash-lite,openai:gpt-4o-mini,anthropic:claude-haiku-4-5-20251001"

Requires the corresponding API keys:
    GOOGLE_API_KEY / GEMINI_API_KEY   for google_genai
    OPENAI_API_KEY                    for openai
    ANTHROPIC_API_KEY                 for anthropic

LangSmith tracing (optional):
    LANGCHAIN_TRACING_V2=true
    LANGCHAIN_API_KEY=<key>
"""
import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.timeout(600)

from tests.evaluators.ats_evaluator import ATSEvaluator
from tests.evaluators.llm_judge import LLMJudge
from tests.evaluators.report import ResumeEvaluationReport, print_comparison_table
from tests.evaluators.schema_evaluator import SchemaEvaluator
from tests.fixtures.job_descriptions import JD_SOFTWARE_ENGINEER_SENIOR


@pytest.mark.real_ai
@pytest.mark.slow
async def test_multi_model_comparison(mock_pg_vector_tool, models_under_test):
    """
    Generate a resume with each model in --models, score with all evaluators,
    and print a ranked comparison table.

    Hard assertion: every model must produce a schema-valid resume.
    Score values are informational and guide model selection.
    """
    from bot import Bot
    from llm.gemini_agent import GeminiAgent
    from models.resume import ResumeOutputFormat

    judge = LLMJudge()
    reports = []

    for model_string in models_under_test:
        agent = GeminiAgent(
            tools=[mock_pg_vector_tool],
            output_format=ResumeOutputFormat,
            model=model_string,
        )
        bot = Bot(
            writer=MagicMock(),
            llm=agent,
            tool=mock_pg_vector_tool,
            user_id="test_user_001",
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
