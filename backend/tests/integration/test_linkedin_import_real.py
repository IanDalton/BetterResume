import pytest

from tests.fixtures.linkedin_samples import SAMPLE_LINKEDIN_TEXT_FULL

pytestmark = pytest.mark.timeout(60)


@pytest.mark.real_ai
async def test_extract_linkedin_profile_real_model():
    """Full pipeline against a real (cheap) model: sanity-check extraction
    quality against a known sample export, since sanitized fixtures can't
    capture real-world LinkedIn PDF quirks (glyph substitutions, locale
    variance). Run with: pytest --real-ai tests/integration/test_linkedin_import_real.py
    """
    from llm.agent import extract_linkedin_profile

    result = await extract_linkedin_profile(
        SAMPLE_LINKEDIN_TEXT_FULL, model="google-gla:gemini-2.5-flash-lite"
    )

    assert result.profile.full_name and "jane" in result.profile.full_name.lower()
    assert result.profile.email == "jane.doe@example.com"
    assert len(result.experience) >= 2
    companies = {e.company for e in result.experience}
    assert "Acme Corp" in companies
    assert any(e.end_date and e.end_date.lower() == "present" for e in result.experience)
    assert len(result.education) >= 1
    assert len(result.languages) >= 1
