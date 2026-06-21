import re
from dataclasses import dataclass, field
from typing import List

from models.resume import ResumeOutputFormat


@dataclass
class SchemaEvaluationResult:
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    score: float = 0.0


# Real dates are numeric MM/YYYY; a no-digit token is a localized ongoing
# marker like "Present"/"Presente" and is acceptable. Mirrors JobExperience.
_DATE_RE = re.compile(r"^\d{2}/\d{4}$|^\D+$")


class SchemaEvaluator:
    """Validates structural correctness of a ResumeOutputFormat. Offline, deterministic."""

    def evaluate(self, resume: ResumeOutputFormat) -> SchemaEvaluationResult:
        errors: List[str] = []
        warnings: List[str] = []

        if not resume.language or len(resume.language) > 5:
            errors.append(f"language field invalid: {resume.language!r}")

        section = resume.resume_section

        if not section.title or len(section.title.strip()) < 3:
            errors.append("resume_section.title is missing or too short")

        if not section.professional_summary:
            errors.append("professional_summary is missing")
        elif len(section.professional_summary.split()) < 20:
            warnings.append("professional_summary is shorter than 20 words")

        if not section.experience:
            errors.append("experience list is empty")
        else:
            for i, exp in enumerate(section.experience):
                p = f"experience[{i}]"
                if not exp.position:
                    errors.append(f"{p}.position is empty")
                if not exp.company:
                    errors.append(f"{p}.company is empty")
                if not exp.description or len(exp.description) < 50:
                    errors.append(f"{p}.description too short (< 50 chars)")
                if not _DATE_RE.match((exp.start_date or "").strip()):
                    warnings.append(f"{p}.start_date format unexpected: {exp.start_date!r}")
                if not _DATE_RE.match((exp.end_date or "").strip()):
                    warnings.append(f"{p}.end_date format unexpected: {exp.end_date!r}")

        if not section.skills:
            errors.append("skills list is empty")
        else:
            for i, skill in enumerate(section.skills):
                if not skill.name:
                    errors.append(f"skills[{i}].name is empty")
                if not skill.description:
                    warnings.append(f"skills[{i}].description is empty")

        total_checks = 4 + len(section.experience) * 5 + len(section.skills) * 2
        score = max(0.0, 1.0 - len(errors) / max(total_checks, 1))

        return SchemaEvaluationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            score=round(score, 3),
        )
