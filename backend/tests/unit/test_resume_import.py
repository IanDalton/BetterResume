"""Tests for utils.resume_import -- PDF text extraction, boilerplate
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

from tests.fixtures.import_samples import SAMPLE_LINKEDIN_TEXT_FULL
from utils.resume_import import (
    ResumeImportResult,
    ResumePdfEmptyError,
    _clean_text,
    entries_with_date_like_descriptions,
    extract_text_from_pdf,
    looks_like_date_line,
    parse_resume_pdf,
    strip_date_like_descriptions,
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
    with patch("utils.resume_import.PdfReader", return_value=_fake_reader(["Jane Doe\n" * 10, "Experience\n" * 10])):
        text = extract_text_from_pdf(b"fake-pdf-bytes")
    assert "Jane Doe" in text
    assert "Experience" in text


def test_extract_text_from_pdf_raises_on_empty_text():
    with patch("utils.resume_import.PdfReader", return_value=_fake_reader(["", ""])):
        with pytest.raises(ResumePdfEmptyError):
            extract_text_from_pdf(b"fake-pdf-bytes")


def test_extract_text_from_pdf_raises_on_unreadable_file():
    with patch("utils.resume_import.PdfReader", side_effect=Exception("not a pdf")):
        with pytest.raises(ResumePdfEmptyError):
            extract_text_from_pdf(b"not-a-real-pdf")


def test_extract_text_from_pdf_handles_none_extract_result():
    # pypdf's extract_text() can return None for some malformed pages.
    reader = MagicMock()
    page = MagicMock()
    page.extract_text.return_value = None
    reader.pages = [page]
    with patch("utils.resume_import.PdfReader", return_value=reader):
        with pytest.raises(ResumePdfEmptyError):
            extract_text_from_pdf(b"fake-pdf-bytes")


# ---------------------------------------------------------------------------
# _clean_text
# ---------------------------------------------------------------------------

def test_clean_text_strips_page_numbers_but_keeps_urls():
    raw = "Jane Doe\n\nPage 1\nPage 2 of 3\nwww.linkedin.com/in/janedoe\n\nExperience\n"
    cleaned = _clean_text(raw)
    assert "Page 1" not in cleaned
    assert "Page 2 of 3" not in cleaned
    # URLs are kept: they become profile links in the extraction.
    assert "www.linkedin.com/in/janedoe" in cleaned
    assert "Jane Doe" in cleaned
    assert "Experience" in cleaned


def test_clean_text_drops_blank_lines():
    raw = "Jane Doe\n\n\n\nExperience"
    cleaned = _clean_text(raw)
    assert cleaned == "Jane Doe\nExperience"


# ---------------------------------------------------------------------------
# parse_resume_pdf orchestration
# ---------------------------------------------------------------------------

async def test_parse_resume_pdf_returns_structured_result():
    sample_result = ResumeImportResult(
        profile={"full_name": "Jane Doe", "email": "jane@example.com", "links": []},
        experience=[{"type": "job", "company": "Acme Corp", "role": "Engineer", "description": "Built things"}],
        education=[],
        skills=["Python"],
        languages=[{"name": "English", "proficiency": "Native"}],
        warnings=[],
    )
    model = TestModel(custom_output_args=sample_result.model_dump())

    with patch("utils.resume_import.PdfReader", return_value=_fake_reader([SAMPLE_LINKEDIN_TEXT_FULL])):
        result = await parse_resume_pdf(b"fake-pdf-bytes", model=model)

    assert isinstance(result, ResumeImportResult)
    assert result.profile.full_name == "Jane Doe"
    assert result.experience[0].company == "Acme Corp"
    assert result.languages[0].name == "English"


async def test_parse_resume_pdf_propagates_empty_pdf_error_before_llm_call():
    """An empty/unreadable PDF must short-circuit before any LLM call is attempted."""
    with patch("utils.resume_import.PdfReader", return_value=_fake_reader(["", ""])):
        with pytest.raises(ResumePdfEmptyError):
            await parse_resume_pdf(b"fake-pdf-bytes", model=TestModel())


# ---------------------------------------------------------------------------
# Date-like description detection / cleanup (the "description is just the
# duration" failure mode of smaller models)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "July 2025 - Present (1 year 1 month)",
    "February 2023 - December 2023 (11 months)",
    "ago. de 2024 - actualidad (1 año 1 mes)",
    "Mar 2021 - Present (3 years 4 months)",
    "3 years 2 months",
    "11 months",
])
def test_looks_like_date_line_matches_date_and_duration_lines(line):
    assert looks_like_date_line(line)


@pytest.mark.parametrize("line", [
    "Led migration to containerized infrastructure, reducing deployment time by 60%.",
    "Saved over 120+ man-hours per week and improved operational flow.",
    "Built REST APIs in Python/FastAPI serving 50k req/s with 99.9% uptime.",
    "Managed 5 groups of students across two campuses.",
    "",
])
def test_looks_like_date_line_keeps_real_descriptions(line):
    assert not looks_like_date_line(line)


def _result_with_descriptions(*descriptions):
    return ResumeImportResult(
        experience=[
            {"type": "job", "company": f"Co{i}", "role": f"Role{i}", "description": d}
            for i, d in enumerate(descriptions)
        ],
    )


def test_entries_with_date_like_descriptions_flags_only_offenders():
    result = _result_with_descriptions(
        "July 2025 - Present (1 year 1 month)",
        "Shipped the flux capacitor.",
        "",
    )
    offenders = entries_with_date_like_descriptions(result)
    assert [e.company for e in offenders] == ["Co0"]


def test_strip_date_like_descriptions_blanks_and_warns():
    result = _result_with_descriptions(
        "July 2025 - Present (1 year 1 month)",
        "Shipped the flux capacitor.",
    )
    strip_date_like_descriptions(result)
    assert result.experience[0].description == ""
    assert result.experience[1].description == "Shipped the flux capacitor."
    assert len(result.warnings) == 1
    assert "Role0 at Co0" in result.warnings[0]


def test_strip_date_like_descriptions_keeps_mixed_content_without_warning():
    result = _result_with_descriptions(
        "July 2025 - Present (1 year 1 month)\nShipped the flux capacitor.",
    )
    strip_date_like_descriptions(result)
    assert result.experience[0].description == "Shipped the flux capacitor."
    assert result.warnings == []


async def test_parse_resume_pdf_sanitizes_persistent_date_like_descriptions():
    """The output validator asks the model to retry; a model that keeps
    returning date-like descriptions (TestModel always echoes the same output)
    must end with stripped descriptions + a warning, not a failed import."""
    bad_result = _result_with_descriptions("July 2025 - Present (1 year 1 month)")
    model = TestModel(custom_output_args=bad_result.model_dump())

    with patch("utils.resume_import.PdfReader", return_value=_fake_reader([SAMPLE_LINKEDIN_TEXT_FULL])):
        result = await parse_resume_pdf(b"fake-pdf-bytes", model=model)

    assert result.experience[0].description == ""
    assert any("Role0 at Co0" in w for w in result.warnings)
