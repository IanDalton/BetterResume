"""Tests for utils.linkedin_import -- PDF text extraction, boilerplate
cleanup, and the structured-extraction orchestration.

No binary PDF fixtures are used (this repo's fixtures are plain Python
literals -- see tests/fixtures/); pypdf's PdfReader is mocked instead so the
tests exercise the actual extraction/cleaning/orchestration logic without
depending on a hand-authored binary file that can't be verified in this
environment.
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.models.test import TestModel

from tests.fixtures.linkedin_samples import SAMPLE_LINKEDIN_TEXT_FULL
from utils.linkedin_import import (
    LinkedInImportResult,
    LinkedInPdfEmptyError,
    _clean_text,
    extract_text_from_pdf,
    parse_linkedin_pdf,
)


def _fake_reader(pages_text):
    reader = MagicMock()
    pages = []
    for text in pages_text:
        page = MagicMock()
        page.extract_text.return_value = text
        pages.append(page)
    reader.pages = pages
    return reader


# ---------------------------------------------------------------------------
# extract_text_from_pdf
# ---------------------------------------------------------------------------

def test_extract_text_from_pdf_joins_pages():
    with patch("utils.linkedin_import.PdfReader", return_value=_fake_reader(["Jane Doe\n" * 10, "Experience\n" * 10])):
        text = extract_text_from_pdf(b"fake-pdf-bytes")
    assert "Jane Doe" in text
    assert "Experience" in text


def test_extract_text_from_pdf_raises_on_empty_text():
    with patch("utils.linkedin_import.PdfReader", return_value=_fake_reader(["", ""])):
        with pytest.raises(LinkedInPdfEmptyError):
            extract_text_from_pdf(b"fake-pdf-bytes")


def test_extract_text_from_pdf_raises_on_unreadable_file():
    with patch("utils.linkedin_import.PdfReader", side_effect=Exception("not a pdf")):
        with pytest.raises(LinkedInPdfEmptyError):
            extract_text_from_pdf(b"not-a-real-pdf")


def test_extract_text_from_pdf_handles_none_extract_result():
    # pypdf's extract_text() can return None for some malformed pages.
    reader = MagicMock()
    page = MagicMock()
    page.extract_text.return_value = None
    reader.pages = [page]
    with patch("utils.linkedin_import.PdfReader", return_value=reader):
        with pytest.raises(LinkedInPdfEmptyError):
            extract_text_from_pdf(b"fake-pdf-bytes")


# ---------------------------------------------------------------------------
# _clean_text
# ---------------------------------------------------------------------------

def test_clean_text_strips_page_numbers_and_profile_url():
    raw = "Jane Doe\n\nPage 1\nwww.linkedin.com/in/janedoe\n\nExperience\n"
    cleaned = _clean_text(raw)
    assert "Page 1" not in cleaned
    assert "linkedin.com/in/janedoe" not in cleaned
    assert "Jane Doe" in cleaned
    assert "Experience" in cleaned


def test_clean_text_drops_blank_lines():
    raw = "Jane Doe\n\n\n\nExperience"
    cleaned = _clean_text(raw)
    assert cleaned == "Jane Doe\nExperience"


# ---------------------------------------------------------------------------
# parse_linkedin_pdf orchestration
# ---------------------------------------------------------------------------

async def test_parse_linkedin_pdf_returns_structured_result():
    sample_result = LinkedInImportResult(
        profile={"full_name": "Jane Doe", "email": "jane@example.com", "links": []},
        experience=[{"type": "job", "company": "Acme Corp", "role": "Engineer", "description": "Built things"}],
        education=[],
        skills=["Python"],
        languages=[{"name": "English", "proficiency": "Native"}],
        warnings=[],
    )
    model = TestModel(custom_output_args=sample_result.model_dump())

    with patch("utils.linkedin_import.PdfReader", return_value=_fake_reader([SAMPLE_LINKEDIN_TEXT_FULL])):
        result = await parse_linkedin_pdf(b"fake-pdf-bytes", model=model)

    assert isinstance(result, LinkedInImportResult)
    assert result.profile.full_name == "Jane Doe"
    assert result.experience[0].company == "Acme Corp"
    assert result.languages[0].name == "English"


async def test_parse_linkedin_pdf_propagates_empty_pdf_error_before_llm_call():
    """An empty/unreadable PDF must short-circuit before any LLM call is attempted."""
    with patch("utils.linkedin_import.PdfReader", return_value=_fake_reader(["", ""])):
        with pytest.raises(LinkedInPdfEmptyError):
            await parse_linkedin_pdf(b"fake-pdf-bytes", model=TestModel())
