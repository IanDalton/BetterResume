"""Parses a LinkedIn "Save to PDF" profile export into structured data for
review before anything is saved (see api/routers/linkedin_import.py).

True OAuth-based LinkedIn import isn't possible for third-party apps --
LinkedIn's public API only grants name/email/photo, never work history.
The realistic, ToS-compliant path is: the user exports their own profile
as a PDF and uploads it here.

Extraction approach: pypdf text extraction (LinkedIn's export is simple
single-column text, so pdfplumber's layout-analysis strength buys nothing)
followed by a single pydantic-ai structured-output call -- far more robust
to LinkedIn's locale/format variance (translated section headers, "Present"
vs "Actualidad", month-name dates) than regex/heuristic parsing, and this
codebase already has the pydantic-ai plumbing for exactly this kind of
forced structured extraction (see llm/agent.py).
"""

import io
import logging
from typing import List, Optional

from pydantic import BaseModel
from pypdf import PdfReader

logger = logging.getLogger("betterresume.linkedin_import")

MIN_TEXT_CHARS = 40


class LinkedInPdfEmptyError(Exception):
    """No meaningful extractable text (e.g. a scanned/image-only PDF)."""


class LinkedInLink(BaseModel):
    kind: str = "other"
    label: Optional[str] = None
    url: str


class LinkedInProfileFields(BaseModel):
    full_name: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    links: List[LinkedInLink] = []


class LinkedInEntry(BaseModel):
    """Shaped like backend/api/schemas.py's JobRecord (type/company/role/etc.)
    without importing it -- utils/ must not depend on api/ (see api/routers/
    linkedin_import.py for the conversion at the API boundary)."""
    type: str  # "job" | "education"
    company: str
    description: str
    role: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class LinkedInLanguage(BaseModel):
    name: str
    proficiency: Optional[str] = None


class LinkedInImportResult(BaseModel):
    profile: LinkedInProfileFields = LinkedInProfileFields()
    experience: List[LinkedInEntry] = []
    education: List[LinkedInEntry] = []
    skills: List[str] = []
    languages: List[LinkedInLanguage] = []
    warnings: List[str] = []


def extract_text_from_pdf(content: bytes) -> str:
    """Extract raw text from a PDF's pages.

    Raises LinkedInPdfEmptyError if the file isn't a readable PDF or has no
    meaningful extractable text (e.g. scanned/image-only), so callers can
    short-circuit before ever spending an LLM call on it.
    """
    try:
        reader = PdfReader(io.BytesIO(content))
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise LinkedInPdfEmptyError("Could not read this file as a PDF") from exc
    text = "\n".join(pages_text)
    if len(text.strip()) < MIN_TEXT_CHARS:
        raise LinkedInPdfEmptyError("No readable text found in this PDF")
    return text


def _clean_text(raw: str) -> str:
    """Strip LinkedIn export boilerplate (page numbers, profile-URL footer
    lines) and blank lines, to cut noise/tokens before the LLM call."""
    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        low = stripped.lower()
        if low.startswith("page ") and low[5:].strip().isdigit():
            continue
        if low.startswith("www.linkedin.com/in/") or low.startswith("linkedin.com/in/"):
            continue
        lines.append(stripped)
    return "\n".join(lines)


async def parse_linkedin_pdf(content: bytes, *, model=None) -> LinkedInImportResult:
    """Extract structured profile/experience/education/language data from a
    LinkedIn PDF export. Raises LinkedInPdfEmptyError for unreadable/empty PDFs;
    propagates any LLM/extraction failure for the caller to translate into an
    HTTP error (see api/routers/linkedin_import.py).
    """
    # Local import: llm.agent imports LinkedInImportResult from this module for
    # its output_type, so importing it back at module load time here would cycle.
    from llm.agent import extract_linkedin_profile

    raw_text = extract_text_from_pdf(content)
    cleaned = _clean_text(raw_text)
    logger.info("Extracted %d chars of cleaned text from LinkedIn PDF", len(cleaned))
    return await extract_linkedin_profile(cleaned, model=model)
