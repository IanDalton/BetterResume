"""Turn a parsed resume PDF (`ResumeImportResult`, the shape the import
endpoint returns for review) into the `ResumeOutputFormat` the analysis
pipeline scores, so a user can get an ATS score for a resume they already
have without generating one first.

Nothing is invented: every field comes from the parsed document, and a
resume with no work experience is rejected rather than padded.
"""

import re
from datetime import datetime
from typing import List, Optional

from pydantic import ValidationError

from models.education import Education
from models.job_experience import JobExperience
from models.language import Language
from models.resume import ResumeOutputFormat
from models.resume_section import ResumeSection
from models.skill import Skill
from utils.resume_import import ImportedEntry, ResumeImportResult


class NoExperienceError(ValueError):
    """The parsed resume has no work-experience entries to score."""


# The import prompt normalizes dates to DD/MM/YYYY (or "present"); the other
# shapes cover what a model returns when it does not quite comply.
_DATE_FORMATS = ("%d/%m/%Y", "%m/%Y", "%Y-%m-%d", "%Y-%m", "%B %Y", "%b %Y", "%Y")


def to_resume_date(value: Optional[str]) -> str:
    """Map an imported date onto the MM/YYYY form `JobExperience` accepts. A
    token without digits (\"present\", \"Actualidad\") passes through as the
    ongoing marker; an unparseable date becomes empty rather than failing the
    whole analysis."""
    text = (value or "").strip()
    if not text:
        return ""
    if not any(ch.isdigit() for ch in text):
        return text
    cleaned = re.sub(r"\s+", " ", text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%m/%Y")
        except ValueError:
            continue
    match = re.search(r"(0?[1-9]|1[0-2])[/-](\d{4})", cleaned)
    if match:
        return f"{int(match.group(1)):02d}/{match.group(2)}"
    match = re.search(r"\b(19|20)\d{2}\b", cleaned)
    if match:
        return f"01/{match.group(0)}"
    return ""


def _experience(entry: ImportedEntry) -> JobExperience:
    return JobExperience(
        position=(entry.role or "").strip(),
        company=(entry.company or "").strip(),
        location=(entry.location or "").strip(),
        start_date=to_resume_date(entry.start_date),
        end_date=to_resume_date(entry.end_date),
        description=(entry.description or "").strip(),
    )


def _education(entry: ImportedEntry) -> Education:
    dates = " - ".join(d for d in (to_resume_date(entry.start_date), to_resume_date(entry.end_date)) if d)
    return Education(
        institution=(entry.company or "").strip(),
        degree=(entry.role or entry.description or "").strip(),
        dates=dates,
    )


def imported_to_resume(parsed: ResumeImportResult, *, language: str = "en") -> ResumeOutputFormat:
    experience: List[JobExperience] = [_experience(e) for e in parsed.experience]
    if not experience:
        raise NoExperienceError("No work experience found in the resume")

    profile = parsed.profile
    title = (profile.headline or "").strip() or experience[0].position or "Resume"
    skills = [Skill(name=name.strip(), description="") for name in parsed.skills if name and name.strip()]
    fields = dict(
        title=title,
        professional_summary=(profile.summary or "").strip(),
        experience=experience,
        skills=skills,
        education=[_education(e) for e in parsed.education],
        languages=[Language(name=l.name, proficiency=l.proficiency or "") for l in parsed.languages if l.name],
    )
    try:
        section = ResumeSection(**fields)
    except ValidationError:
        # The generation schema insists on at least one skill; an existing
        # resume may simply have no skills section. Score it as it is (the
        # reviewer will say so) instead of inventing a skill to pass validation.
        section = ResumeSection.model_construct(**fields)
    return ResumeOutputFormat(language=(language or "en")[:5], resume_section=section)
