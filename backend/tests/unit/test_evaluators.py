import copy

import pytest

from evals.evaluators.ats_evaluator import ATSEvaluator
from evals.evaluators.schema_evaluator import SchemaEvaluator
from tests.fixtures.job_descriptions import JD_SOFTWARE_ENGINEER_SENIOR


def test_ats_keyword_coverage_senior_swe(sample_resume_output):
    result = ATSEvaluator().evaluate(sample_resume_output, JD_SOFTWARE_ENGINEER_SENIOR)
    assert result.keyword_coverage >= 0.15, (
        f"Expected ≥15% keyword coverage, got {result.keyword_coverage:.2f}. "
        f"Missing: {result.missing_keywords[:5]}"
    )
    assert result.score >= 0.3


def test_ats_detects_missing_keywords(sample_resume_output):
    jd = "Requires: React, TypeScript, GraphQL, Next.js, Tailwind CSS"
    result = ATSEvaluator().evaluate(sample_resume_output, jd)
    missing_lower = {k.lower() for k in result.missing_keywords}
    assert "react" in missing_lower or "typescript" in missing_lower, (
        "Expected React or TypeScript in missing keywords"
    )


def test_ats_flags_vague_language(sample_resume_output):
    resume = copy.deepcopy(sample_resume_output)
    resume.resume_section.experience[0].description = (
        "- Responsible for doing various backend tasks\n"
        "- Helped with database optimization and excellent performance improvements"
    )
    result = ATSEvaluator().evaluate(resume, JD_SOFTWARE_ENGINEER_SENIOR)
    assert any(
        "vague" in issue or "responsible" in issue
        for issue in result.formatting_issues
    )


def test_ats_flags_no_action_verbs(sample_resume_output):
    resume = copy.deepcopy(sample_resume_output)
    resume.resume_section.experience[0].description = (
        "- Worked on microservices using Kafka\n"
        "- Involved in Kubernetes migration project"
    )
    result = ATSEvaluator().evaluate(resume, JD_SOFTWARE_ENGINEER_SENIOR)
    assert any("action verbs" in issue for issue in result.formatting_issues)


def test_ats_flags_insufficient_bullets(sample_resume_output):
    resume = copy.deepcopy(sample_resume_output)
    resume.resume_section.experience[0].description = (
        "- Designed and implemented the entire microservices platform single-handedly"
    )
    result = ATSEvaluator().evaluate(resume, JD_SOFTWARE_ENGINEER_SENIOR)
    assert any("fewer than 2 bullet" in issue for issue in result.formatting_issues)


def test_schema_score_is_high_for_valid_resume(sample_resume_output):
    result = SchemaEvaluator().evaluate(sample_resume_output)
    assert result.score >= 0.9
    assert result.passed


def test_composite_score_without_judge(sample_resume_output):
    from evals.evaluators.report import ResumeEvaluationReport
    schema = SchemaEvaluator().evaluate(sample_resume_output)
    ats = ATSEvaluator().evaluate(sample_resume_output, JD_SOFTWARE_ENGINEER_SENIOR)
    report = ResumeEvaluationReport(
        model="test-model",
        jd_name="senior_swe",
        schema=schema,
        ats=ats,
    )
    assert 0.0 <= report.composite_score <= 1.0
    assert report.composite_score > 0.3


async def test_llm_judge_aevaluate_uses_agent(sample_resume_output):
    from pydantic_ai.models.test import TestModel
    from evals.evaluators.llm_judge import LLMJudge

    judge = LLMJudge(judge_model=TestModel(custom_output_args={
        "relevance": 8, "quality": 7, "coherence": 9, "reasoning": "Solid match.",
    }))
    result = await judge.aevaluate(sample_resume_output, "Senior Python engineer")

    assert result.relevance_score == 0.8
    assert result.overall_score == pytest.approx((0.8 + 0.7 + 0.9) / 3, abs=1e-3)
