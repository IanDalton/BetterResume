import pytest
from pydantic import ValidationError

from models.job_experience import JobExperience


def _make(date: str) -> JobExperience:
    return JobExperience(
        position="Engineer",
        company="Acme Corp",
        location="Remote",
        start_date=date,
        end_date=date,
        description=(
            "Built and shipped features using Python and FastAPI, "
            "improving throughput by 30% and reducing latency."
        ),
    )


@pytest.mark.parametrize("date", ["10/2024", "01/1999", "12/2025"])
def test_numeric_mm_yyyy_accepted(date):
    assert _make(date).start_date == date


@pytest.mark.parametrize("date", ["Present", "Presente", "Présent", "Heute", "Actuel"])
def test_localized_present_token_accepted(date):
    # The agent writes the ongoing-role marker in the resume's own language;
    # any digit-free token is allowed.
    assert _make(date).end_date == date


@pytest.mark.parametrize("date", ["", "   "])
def test_empty_date_allowed(date):
    assert _make(date).end_date == date


@pytest.mark.parametrize("date", ["13/2024", "2024/10", "10-2024", "5/24", "Octubre 2024", "2021-03"])
def test_malformed_numeric_date_rejected(date):
    # Anything containing digits must be valid MM/YYYY — this catches localized
    # month-name dates like "Octubre 2024", which would not be sortable.
    with pytest.raises(ValidationError):
        _make(date)
