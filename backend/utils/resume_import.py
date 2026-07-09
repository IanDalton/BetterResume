"""Parses an uploaded resume/CV PDF into structured data for review before
anything is saved (see api/routers/resume_import.py).

Works for any text-based resume PDF, including LinkedIn profile exports
("Save to PDF" -- the realistic, ToS-compliant import path, since LinkedIn's
public API only grants name/email/photo, never work history).

Extraction approach: pypdf text extraction followed by a single pydantic-ai
structured-output call -- far more robust to layout and locale variance
(arbitrary resume formats, translated section headers, "Present" vs
"Actualidad", month-name dates) than regex/heuristic parsing, and this
codebase already has the pydantic-ai plumbing for exactly this kind of
forced structured extraction (see llm/agent.py).
"""

import asyncio
import io
import logging
import re
from typing import List, Optional

from pydantic import BaseModel, Field
from pypdf import PdfReader

logger = logging.getLogger("betterresume.resume_import")

MIN_TEXT_CHARS = 40


class ResumePdfEmptyError(Exception):
    """No meaningful extractable text (e.g. a scanned/image-only PDF)."""


class ImportedLink(BaseModel):
    kind: str = "other"
    label: Optional[str] = None
    url: str


class ImportedProfileFields(BaseModel):
    full_name: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    links: List[ImportedLink] = []


class ImportedEntry(BaseModel):
    """Shaped like backend/api/schemas.py's JobRecord (type/company/role/etc.)
    without importing it -- utils/ must not depend on api/. The import router
    returns these models directly as its response schema."""
    type: str  # "job" | "education"
    company: str
    description: str = Field(
        description=(
            "The descriptive bullet/summary text under this entry, copied verbatim. "
            "NEVER the date range or duration line (e.g. 'July 2025 - Present (1 year 1 month)') "
            "-- dates belong only in start_date/end_date and the duration is discarded. "
            "Empty string if the entry has no descriptive text."
        )
    )
    role: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ImportedLanguage(BaseModel):
    name: str
    proficiency: Optional[str] = None


class ResumeImportResult(BaseModel):
    profile: ImportedProfileFields = ImportedProfileFields()
    experience: List[ImportedEntry] = []
    education: List[ImportedEntry] = []
    skills: List[str] = []
    languages: List[ImportedLanguage] = []
    warnings: List[str] = []


# The date line of a resume entry is "<start> - <end>", often with a duration,
# e.g. "July 2025 - Present (1 year 1 month)" / "ago. de 2024 - actualidad (1 año)".
# Small models tend to copy it into `description`; these patterns detect that so the
# output validator in llm/agent.py can force a retry (see ensure_real_descriptions).
_DATE_RANGE_LINE_RE = re.compile(r"^[^()\n]{1,60}\s[-–—]\s[^()\n]{1,60}\(\d[^)]{0,40}\)$")
# A LinkedIn company grouping several roles gets a bare total-duration line,
# e.g. "3 years 2 months".
_BARE_DURATION_RE = re.compile(r"^\d+\s+\w+(?:\s+\d+\s+\w+)?$")


def looks_like_date_line(text: str) -> bool:
    """True if a line is a date-range/duration line rather than real
    descriptive text."""
    stripped = text.strip()
    return bool(_DATE_RANGE_LINE_RE.match(stripped) or _BARE_DURATION_RE.match(stripped))


def entries_with_date_like_descriptions(result: "ResumeImportResult") -> List[ImportedEntry]:
    """Entries whose description consists entirely of date-range/duration lines
    (the model put the dates where the bullets belong)."""
    offenders = []
    for entry in [*result.experience, *result.education]:
        lines = [l for l in entry.description.splitlines() if l.strip()]
        if lines and all(looks_like_date_line(l) for l in lines):
            offenders.append(entry)
    return offenders


def strip_date_like_descriptions(result: "ResumeImportResult") -> "ResumeImportResult":
    """Last-resort cleanup: remove date-range/duration lines from descriptions in
    place, blanking descriptions that contained nothing else, and record a warning
    for each affected entry."""
    for entry in [*result.experience, *result.education]:
        lines = [l for l in entry.description.splitlines() if l.strip()]
        kept = [l for l in lines if not looks_like_date_line(l)]
        if len(kept) != len(lines):
            entry.description = "\n".join(kept)
            if not kept:
                label = f"{entry.role} at {entry.company}" if entry.role else entry.company
                result.warnings.append(
                    f"Could not extract a description for '{label}' -- it may need to be filled in manually."
                )
    return result


def extract_text_from_pdf(content: bytes) -> str:
    """Extract raw text from a PDF's pages.

    Raises ResumePdfEmptyError if the file isn't a readable PDF or has no
    meaningful extractable text (e.g. scanned/image-only), so callers can
    short-circuit before ever spending an LLM call on it.
    """
    try:
        reader = PdfReader(io.BytesIO(content))
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise ResumePdfEmptyError("Could not read this file as a PDF") from exc
    text = "\n".join(pages_text)
    if len(text.strip()) < MIN_TEXT_CHARS:
        raise ResumePdfEmptyError("No readable text found in this PDF")
    return text


_PAGE_NUMBER_RE = re.compile(r"^page\s+\d+(\s+of\s+\d+)?$", re.IGNORECASE)


def _clean_text(raw: str) -> str:
    """Strip page-number boilerplate lines ("Page 3", "Page 1 of 3") and blank
    lines, to cut noise/tokens before the LLM call. URLs are deliberately kept:
    they become profile links."""
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _PAGE_NUMBER_RE.match(stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)


async def parse_resume_pdf(content: bytes, *, model=None) -> ResumeImportResult:
    """Extract structured profile/experience/education/language data from a
    resume PDF. Raises ResumePdfEmptyError for unreadable/empty PDFs;
    propagates any LLM/extraction failure for the caller to translate into an
    HTTP error (see api/routers/resume_import.py).
    """
    # Local import: llm.agent imports ResumeImportResult from this module for
    # its output_type, so importing it back at module load time here would cycle.
    from llm.agent import extract_resume_fields

    # pypdf extraction is CPU-bound (can take seconds on multi-page resumes);
    # run it off the event loop so it doesn't stall concurrent requests.
    raw_text = await asyncio.to_thread(extract_text_from_pdf, content)
    cleaned = _clean_text(raw_text)
    logger.info("Extracted %d chars of cleaned text from resume PDF", len(cleaned))
    return await extract_resume_fields(cleaned, model=model)
