import re
from dataclasses import dataclass, field
from typing import List, Set

from models.resume import ResumeOutputFormat


@dataclass
class ATSEvaluationResult:
    score: float
    keyword_coverage: float
    matched_keywords: List[str] = field(default_factory=list)
    missing_keywords: List[str] = field(default_factory=list)
    formatting_issues: List[str] = field(default_factory=list)


ACTION_VERBS = {
    "led", "built", "designed", "developed", "implemented", "optimized",
    "managed", "reduced", "increased", "delivered", "launched", "scaled",
    "mentored", "collaborated", "automated", "migrated", "improved",
    "architected", "deployed", "created", "streamlined", "established",
    "spearheaded", "drove", "facilitated", "coordinated", "executed",
}

_VAGUE = [
    (r"\bresponsible for\b", "responsible for"),
    (r"\bhelped with\b", "helped with"),
    (r"\bassisted in\b", "assisted in"),
    (r"\bvarious\b", "various"),
    (r"\bexcellent\b", "excellent"),
    (r"\bgood\b", "good"),
]

_STOP_WORDS = {
    "and", "the", "for", "with", "you", "our", "are", "will", "have",
    "this", "that", "from", "your", "they", "we", "to", "of", "in",
    "a", "an", "is", "be", "as", "at", "or", "on", "by", "it", "its",
    "not", "but", "can", "do", "has", "was", "who", "us", "any", "all",
    "new", "also", "than", "more", "over", "per", "via", "able",
}


class ATSEvaluator:
    """Evaluates ATS optimization: keyword coverage and bullet formatting. Offline."""

    def evaluate(self, resume: ResumeOutputFormat, job_description: str) -> ATSEvaluationResult:
        resume_text = self._resume_to_text(resume).lower()
        jd_keywords = self._extract_keywords(job_description)

        matched = [kw for kw in jd_keywords if kw.lower() in resume_text]
        missing = [kw for kw in jd_keywords if kw.lower() not in resume_text]
        coverage = len(matched) / max(len(jd_keywords), 1)

        formatting_issues = self._check_formatting(resume)
        formatting_score = max(0.0, 1.0 - len(formatting_issues) / 5)
        score = 0.7 * coverage + 0.3 * formatting_score

        return ATSEvaluationResult(
            score=round(score, 3),
            keyword_coverage=round(coverage, 3),
            matched_keywords=matched,
            missing_keywords=missing,
            formatting_issues=formatting_issues,
        )

    def _resume_to_text(self, resume: ResumeOutputFormat) -> str:
        parts = [resume.resume_section.title, resume.resume_section.professional_summary]
        for exp in resume.resume_section.experience:
            parts.extend([exp.position, exp.company, exp.description or ""])
        for skill in resume.resume_section.skills:
            parts.extend([skill.name, skill.description or ""])
        return " ".join(parts)

    def _extract_keywords(self, jd: str) -> List[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9+#\.]{2,}", jd)
        seen: Set[str] = set()
        result = []
        for t in tokens:
            lower = t.lower()
            if lower not in _STOP_WORDS and lower not in seen:
                seen.add(lower)
                result.append(t)
        return result[:40]

    def _check_formatting(self, resume: ResumeOutputFormat) -> List[str]:
        issues = []
        for i, exp in enumerate(resume.resume_section.experience):
            desc = exp.description or ""
            lines = [l.strip() for l in desc.split("\n") if l.strip()]
            bullet_lines = [l for l in lines if l.startswith(("-", "•", "*"))]

            if bullet_lines:
                first_words = {l.lstrip("-•* ").split()[0].lower() for l in bullet_lines if l.split()}
                if not first_words & ACTION_VERBS:
                    issues.append(f"experience[{i}]: no recognized action verbs in bullets")

            for pattern, label in _VAGUE:
                if re.search(pattern, desc, re.IGNORECASE):
                    issues.append(f"experience[{i}]: vague language detected ({label!r})")
                    break

            if len(bullet_lines) < 2:
                issues.append(f"experience[{i}]: fewer than 2 bullet points")

        return issues
