import copy

import pytest
from pydantic import ValidationError

from models.resume import ResumeOutputFormat
from models.resume_section import ResumeSection
from models.skill import Skill
from tests.evaluators.schema_evaluator import SchemaEvaluator


def test_valid_resume_passes_schema(sample_resume_output):
    result = SchemaEvaluator().evaluate(sample_resume_output)
    assert result.passed, f"Unexpected errors: {result.errors}"
    assert result.score >= 0.9


def test_missing_experience_raises_pydantic_error():
    with pytest.raises(ValidationError):
        ResumeSection(
            title="Engineer",
            professional_summary=(
                "Experienced engineer with strong background in distributed systems and Python. "
                "Led multiple teams and delivered high-impact projects at scale."
            ),
            experience=[],
            skills=[Skill(name="Python", description="Used daily in production systems")],
            education=[],
        )


def test_missing_skills_raises_pydantic_error():
    with pytest.raises(ValidationError):
        ResumeSection(
            title="Engineer",
            professional_summary=(
                "Experienced engineer with strong background in distributed systems and Python. "
                "Led multiple teams and delivered high-impact projects at scale."
            ),
            experience=[],
            skills=[],
            education=[],
        )


def test_short_professional_summary_warns(sample_resume_output):
    resume = copy.deepcopy(sample_resume_output)
    resume.resume_section.professional_summary = "Short summary."
    result = SchemaEvaluator().evaluate(resume)
    assert any("professional_summary" in w for w in result.warnings)


def test_invalid_date_format_warns(sample_resume_output):
    resume = copy.deepcopy(sample_resume_output)
    resume.resume_section.experience[0].start_date = "2021-03"
    result = SchemaEvaluator().evaluate(resume)
    assert any("start_date" in w for w in result.warnings)


def test_present_end_date_accepted(sample_resume_output):
    result = SchemaEvaluator().evaluate(sample_resume_output)
    end_date_warnings = [w for w in result.warnings if "end_date" in w and "experience[0]" in w]
    assert not end_date_warnings, f"'Present' should not trigger a date warning: {end_date_warnings}"


def test_empty_description_fails(sample_resume_output):
    resume = copy.deepcopy(sample_resume_output)
    resume.resume_section.experience[0].description = "short"
    result = SchemaEvaluator().evaluate(resume)
    assert not result.passed
    assert any("description" in e for e in result.errors)
