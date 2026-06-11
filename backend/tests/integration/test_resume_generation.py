import pytest
from unittest.mock import MagicMock

from tests.evaluators.ats_evaluator import ATSEvaluator
from tests.evaluators.report import ResumeEvaluationReport
from tests.evaluators.schema_evaluator import SchemaEvaluator
from tests.fixtures.job_descriptions import ALL_JDS, JD_SOFTWARE_ENGINEER_SENIOR, JD_SPANISH_LANGUAGE

pytestmark = pytest.mark.timeout(180)


class _NoEducationDB:
    def get_job_experiences(self, user_id, type_filter=None):
        return []


def _build_bot(stub_vector_store, model: str = "google-gla:gemini-2.5-flash-lite"):
    """Lazy-import Bot/ResumeAgent so collection works without the full Docker env."""
    from bot import Bot
    from llm.agent import ResumeAgent

    agent = ResumeAgent(model=model, vector_store=stub_vector_store, db=_NoEducationDB())
    bot = Bot(
        writer=MagicMock(),
        agent=agent,
        vector_store=stub_vector_store,
        user_id="test_user_001",
        auto_ingest=False,
    )
    return bot


@pytest.mark.real_ai
async def test_generate_resume_schema_valid(stub_vector_store):
    """Full pipeline: real Gemini call → output must pass schema validation."""
    from models.resume import ResumeOutputFormat

    bot = _build_bot(stub_vector_store)
    resume = await bot.generate_resume(JD_SOFTWARE_ENGINEER_SENIOR)

    assert isinstance(resume, ResumeOutputFormat)

    schema = SchemaEvaluator().evaluate(resume)
    ats = ATSEvaluator().evaluate(resume, JD_SOFTWARE_ENGINEER_SENIOR)
    report = ResumeEvaluationReport(
        model="google-gla:gemini-2.5-flash-lite",
        jd_name="senior_swe",
        schema=schema,
        ats=ats,
    )
    report.print_summary()

    assert schema.passed, f"Schema errors: {schema.errors}"
    assert report.composite_score >= 0.4


@pytest.mark.real_ai
@pytest.mark.parametrize("jd_name,jd_text", list(ALL_JDS.items()))
async def test_schema_compliance_across_jds(stub_vector_store, jd_name, jd_text):
    """Each job description variant produces a structurally valid resume."""
    from pydantic import ValidationError

    bot = _build_bot(stub_vector_store)
    try:
        resume = await bot.generate_resume(jd_text)
    except ValidationError as e:
        pytest.fail(f"[{jd_name}] Model returned invalid structure: {e}")

    result = SchemaEvaluator().evaluate(resume)
    assert result.passed, f"[{jd_name}] Schema errors: {result.errors}"


@pytest.mark.real_ai
async def test_resume_language_detected(stub_vector_store):
    """Spanish JD should produce a resume where language is set."""
    from models.resume import ResumeOutputFormat

    bot = _build_bot(stub_vector_store)
    resume = await bot.generate_resume(JD_SPANISH_LANGUAGE)

    assert isinstance(resume, ResumeOutputFormat)
    assert resume.language, "language field must be non-empty"
