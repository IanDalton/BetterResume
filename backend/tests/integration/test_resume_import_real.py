import pytest

from tests.fixtures.import_samples import SAMPLE_CONVENTIONAL_RESUME_TEXT, SAMPLE_LINKEDIN_TEXT_FULL

pytestmark = pytest.mark.timeout(60)

REAL_MODEL = "google:gemini-2.5-flash-lite"


def _assert_no_date_like_descriptions(result):
    """Descriptions must be the real bullets, never the date/duration line
    (a known small-model failure mode -- see ensure_real_descriptions)."""
    from utils.resume_import import looks_like_date_line

    for entry in [*result.experience, *result.education]:
        for line in entry.description.splitlines():
            assert not looks_like_date_line(line), (
                f"date-like description for {entry.role} at {entry.company}: {entry.description!r}"
            )


@pytest.mark.real_ai
async def test_extract_resume_fields_real_model_linkedin_export():
    """Full pipeline against a real (cheap) model: sanity-check extraction
    quality against a known sample export, since sanitized fixtures can't
    capture real-world LinkedIn PDF quirks (glyph substitutions, locale
    variance). Run with: pytest --real-ai tests/integration/test_resume_import_real.py
    """
    from llm.agent import extract_resume_fields

    result = await extract_resume_fields(SAMPLE_LINKEDIN_TEXT_FULL, model=REAL_MODEL)

    assert result.profile.full_name and "jane" in result.profile.full_name.lower()
    assert result.profile.email == "jane.doe@example.com"
    assert len(result.experience) >= 2
    companies = {e.company for e in result.experience}
    assert "Acme Corp" in companies
    assert any(e.end_date and e.end_date.lower() == "present" for e in result.experience)
    assert len(result.education) >= 1
    assert len(result.languages) >= 1

    acme = next(e for e in result.experience if e.company == "Acme Corp")
    assert "containerized" in acme.description
    _assert_no_date_like_descriptions(result)


@pytest.mark.real_ai
async def test_extract_resume_fields_real_model_conventional_resume():
    """Same pipeline against a conventional (non-LinkedIn) resume layout:
    role/company on one line, dates on their own line, bullet markers."""
    from llm.agent import extract_resume_fields

    result = await extract_resume_fields(SAMPLE_CONVENTIONAL_RESUME_TEXT, model=REAL_MODEL)

    assert result.profile.full_name and "john" in result.profile.full_name.lower()
    assert result.profile.email == "john.smith@example.com"
    assert len(result.experience) >= 2
    companies = {e.company for e in result.experience}
    assert "Widget Works" in companies
    widget = next(e for e in result.experience if e.company == "Widget Works")
    assert "Kafka" in widget.description
    assert widget.end_date and widget.end_date.lower() == "present"
    assert len(result.education) >= 1
    assert any("python" in s.lower() for s in result.skills)
    _assert_no_date_like_descriptions(result)
