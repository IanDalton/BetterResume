"""User-facing resume analysis: offline ATS score + LLM review with
recommendations (`llm/resume_analysis.py`, `llm/reviewer.py`)."""

import copy
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.models.test import TestModel

from evals.evaluators.ats_evaluator import ATSEvaluator
from llm import reviewer
from llm.resume_analysis import ResumeAnalysis, analyze_resume, ats_analysis
from tests.fixtures.job_descriptions import JD_SOFTWARE_ENGINEER_SENIOR

REVIEW_OUTPUT = {
    "relevance": 8,
    "quality": 6,
    "coherence": 9,
    "summary": "Strong match with weak metrics.",
    "strengths": ["Clear Kubernetes experience"],
    "recommendations": [
        {
            "section": "experience",
            "severity": "high",
            "issue": "Bullet 3 has no metric",
            "suggestion": "Add the team size or review cadence",
            "experience_index": 0,
        },
        {
            "section": "keywords",
            "severity": "medium",
            "issue": "Terraform missing",
            "suggestion": "List Terraform under skills if you used it",
        },
    ],
    "keywords_to_add": ["Terraform"],
}


# ---------------------------------------------------------------------------
# ATS layer
# ---------------------------------------------------------------------------

def test_ats_evaluator_reports_structured_issues_alongside_text(sample_resume_output):
    resume = copy.deepcopy(sample_resume_output)
    resume.resume_section.experience[0].description = "- Responsible for various backend tasks"
    result = ATSEvaluator().evaluate(resume, JD_SOFTWARE_ENGINEER_SENIOR)

    kinds = {(i.experience_index, i.kind) for i in result.issues}
    assert (0, "vague_language") in kinds
    assert (0, "few_bullets") in kinds
    # The English sentences the eval reports print are still there, one per issue.
    assert len(result.formatting_issues) == len(result.issues)
    assert any("vague" in text for text in result.formatting_issues)


def test_ats_evaluator_ignores_job_posting_boilerplate(sample_resume_output):
    jd = "We are looking for a strong candidate to join our team. Requirements: Kubernetes, Terraform."
    result = ATSEvaluator().evaluate(sample_resume_output, jd)
    missing = {k.lower() for k in result.missing_keywords}
    assert "terraform" in missing
    assert not {"looking", "candidate", "team", "requirements"} & missing


def test_ats_evaluator_matches_education_and_languages(sample_resume_output):
    result = ATSEvaluator().evaluate(sample_resume_output, "Bachelor's degree in Computer Science required")
    assert {"computer", "science"} <= {k.lower() for k in result.matched_keywords}


def test_ats_analysis_is_on_a_0_100_scale(sample_resume_output):
    ats = ats_analysis(sample_resume_output, JD_SOFTWARE_ENGINEER_SENIOR)
    raw = ATSEvaluator().evaluate(sample_resume_output, JD_SOFTWARE_ENGINEER_SENIOR)
    assert ats.score == round(raw.score * 100)
    assert ats.keyword_coverage == round(raw.keyword_coverage * 100)
    assert ats.matched_keywords == raw.matched_keywords
    assert [i.kind for i in ats.issues] == [i.kind for i in raw.issues]


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------

def test_review_prompt_carries_language_and_ats_scan(sample_resume_output):
    prompt = reviewer.build_review_prompt(
        sample_resume_output, "Senior engineer",
        language="es", missing_keywords=["Terraform", "GraphQL"], formatting_issues=["experience[0]: few_bullets"],
    )
    assert "Write all text in: Spanish." in prompt
    assert "Terraform, GraphQL" in prompt
    assert "experience[0]: few_bullets" in prompt
    assert "Senior engineer" in prompt


def test_review_language_defaults_to_the_resume_language(sample_resume_output):
    resume = copy.deepcopy(sample_resume_output)
    resume.language = "pt"
    prompt = reviewer.build_review_prompt(resume, "jd")
    assert "Write all text in: Portuguese." in prompt


async def test_review_uses_the_configured_judge_model(sample_resume_output):
    from llm import model_config

    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:g", "openrouter:g-fallback"),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
        judge=model_config.TaskModels("openrouter:configured/judge", None),
    )
    captured = {}

    async def _fake_run(agent_obj, prompt, *, primary, fallback, on_model_used=None, **kw):
        captured["primary"], captured["fallback"], captured["agent"] = primary, fallback, agent_obj
        raise RuntimeError("stop here")

    with patch("llm.agent.get_model_config", return_value=cfg), \
         patch("llm.reviewer._run_with_fallback", _fake_run), \
         pytest.raises(RuntimeError):
        await reviewer.review(sample_resume_output, "jd")

    assert captured["primary"] == "openrouter:configured/judge"
    assert captured["fallback"] is None
    assert captured["agent"] is reviewer.review_agent


# ---------------------------------------------------------------------------
# Combined analysis
# ---------------------------------------------------------------------------

async def test_analyze_resume_combines_ats_and_review(sample_resume_output):
    analysis = await analyze_resume(
        sample_resume_output, JD_SOFTWARE_ENGINEER_SENIOR,
        language="en", model=TestModel(custom_output_args=REVIEW_OUTPUT),
    )

    assert isinstance(analysis, ResumeAnalysis)
    assert 0 <= analysis.ats.score <= 100
    assert analysis.review_error is None
    review = analysis.review
    assert review is not None
    assert review.scores.relevance == 80
    assert review.scores.quality == 60
    assert review.scores.coherence == 90
    assert review.scores.overall == round((8 + 6 + 9) / 30 * 100)
    assert [r.section for r in review.recommendations] == ["experience", "keywords"]
    assert review.recommendations[0].experience_index == 0
    assert review.keywords_to_add == ["Terraform"]
    assert analysis.model == "test"


async def test_analyze_resume_keeps_ats_when_the_review_fails(sample_resume_output):
    with patch("llm.resume_analysis.review", AsyncMock(side_effect=RuntimeError("judge down"))):
        analysis = await analyze_resume(sample_resume_output, JD_SOFTWARE_ENGINEER_SENIOR)

    assert analysis.review is None
    assert analysis.review_error == "judge down"
    assert analysis.ats.score > 0
    assert analysis.ats.matched_keywords


async def test_analyze_resume_passes_the_ats_scan_to_the_reviewer(sample_resume_output):
    resume = copy.deepcopy(sample_resume_output)
    resume.resume_section.experience[0].description = "- Responsible for various backend tasks"
    fake_review = AsyncMock(return_value=reviewer.ResumeReview(**REVIEW_OUTPUT))

    with patch("llm.resume_analysis.review", fake_review):
        await analyze_resume(resume, "Requires: React, TypeScript", language="es")

    kwargs = fake_review.call_args.kwargs
    assert kwargs["language"] == "es"
    assert {"React", "TypeScript"} <= set(kwargs["missing_keywords"])
    assert any("vague_language" in issue for issue in kwargs["formatting_issues"])


async def test_analyze_resume_can_skip_the_review(sample_resume_output):
    with patch("llm.resume_analysis.review", AsyncMock()) as fake_review:
        analysis = await analyze_resume(sample_resume_output, "jd", include_review=False)
    fake_review.assert_not_called()
    assert analysis.review is None and analysis.review_error is None
