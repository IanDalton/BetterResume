import re
from dataclasses import dataclass, field
from typing import List, Literal, Set

from models.resume import ResumeOutputFormat

IssueKind = Literal["no_action_verbs", "vague_language", "few_bullets"]


@dataclass
class FormattingIssue:
    """One mechanical finding about an experience entry, in a shape the
    frontend can localize (`kind`) rather than the English sentence the eval
    reports print (`formatting_issues`)."""
    experience_index: int
    kind: IssueKind
    detail: str = ""

    def as_text(self) -> str:
        prefix = f"experience[{self.experience_index}]"
        if self.kind == "no_action_verbs":
            return f"{prefix}: no recognized action verbs in bullets"
        if self.kind == "vague_language":
            return f"{prefix}: vague language detected ({self.detail!r})"
        return f"{prefix}: fewer than 2 bullet points"


@dataclass
class ATSEvaluationResult:
    score: float
    keyword_coverage: float
    matched_keywords: List[str] = field(default_factory=list)
    missing_keywords: List[str] = field(default_factory=list)
    formatting_issues: List[str] = field(default_factory=list)
    issues: List[FormattingIssue] = field(default_factory=list)
    # True when the job description text itself looks corrupted (several
    # words mashed together with no whitespace between them -- see
    # `_extract_keywords`), so the UI can say the coverage score may be
    # understated instead of silently scoring garbled text at face value.
    jd_looks_malformed: bool = False


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
    # Job-posting boilerplate: present in nearly every description and never
    # something a resume should be scored on.
    "job", "role", "position", "candidate", "candidates", "team", "teams",
    "company", "join", "work", "working", "experience", "years", "year",
    "skills", "strong", "ability", "including", "etc", "must", "should",
    "looking", "seeking", "required", "requirements", "responsibilities",
    "preferred", "plus", "bonus", "benefits", "salary", "apply", "about",
    "what", "when", "where", "which", "while", "within", "across", "through",
    "their", "them", "these", "those", "into", "such", "each", "other",
    "well", "how", "own", "help", "make", "like", "using", "use", "both",
}

# A single real keyword this long is very unlikely; past this, a token is
# almost certainly several words mashed together with no whitespace (see
# `_extract_keywords`).
_MAX_KEYWORD_LEN = 20
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class ATSEvaluator:
    """Evaluates ATS optimization: keyword coverage and bullet formatting. Offline."""

    def evaluate(self, resume: ResumeOutputFormat, job_description: str) -> ATSEvaluationResult:
        resume_text = self._resume_to_text(resume).lower()
        jd_keywords, jd_looks_malformed = self._extract_keywords(job_description)

        matched = [kw for kw in jd_keywords if kw.lower() in resume_text]
        missing = [kw for kw in jd_keywords if kw.lower() not in resume_text]
        coverage = len(matched) / max(len(jd_keywords), 1)

        issues = self._check_formatting(resume)
        formatting_issues = [issue.as_text() for issue in issues]
        formatting_score = max(0.0, 1.0 - len(formatting_issues) / 5)
        score = 0.7 * coverage + 0.3 * formatting_score

        return ATSEvaluationResult(
            score=round(score, 3),
            keyword_coverage=round(coverage, 3),
            matched_keywords=matched,
            missing_keywords=missing,
            formatting_issues=formatting_issues,
            issues=issues,
            jd_looks_malformed=jd_looks_malformed,
        )

    def _resume_to_text(self, resume: ResumeOutputFormat) -> str:
        section = resume.resume_section
        parts = [section.title, section.professional_summary]
        for exp in section.experience:
            parts.extend([exp.position, exp.company, exp.description or ""])
        for skill in section.skills:
            parts.extend([skill.name, skill.description or ""])
        # Degrees and spoken languages are routinely required by job
        # descriptions ("Bachelor's in Computer Science", "fluent English").
        for edu in section.education:
            parts.extend([edu.institution or "", edu.degree or ""])
        for lang in section.languages:
            parts.extend([lang.name or "", lang.proficiency or ""])
        return " ".join(parts)

    def _extract_keywords(self, jd: str) -> tuple[List[str], bool]:
        raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9+#\.]{2,}", jd)
        tokens: List[str] = []
        anomalies = 0
        for t in raw_tokens:
            # The token class keeps dots so "Node.js" survives, which also
            # keeps a sentence-final dot ("Terraform.") -- strip that, or the
            # keyword never matches and the stop-word check misses "team.".
            t = t.rstrip(".")
            if len(t) > _MAX_KEYWORD_LEN:
                # A job description copy-pasted from a page that lays fields
                # out with CSS (flex/grid) often loses the whitespace
                # between adjacent labels on copy, producing one run like
                # "FullTimeRemoteFlexible". Recover real words at CamelCase
                # boundaries; anything still too long after that is almost
                # certainly several lowercase words mashed together rather
                # than one real keyword, so it's dropped instead of shown.
                anomalies += 1
                tokens.extend(p for p in _CAMEL_BOUNDARY.split(t) if p and len(p) <= _MAX_KEYWORD_LEN)
            else:
                tokens.append(t)

        seen: Set[str] = set()
        result = []
        for t in tokens:
            lower = t.lower()
            if len(lower) < 3:
                continue
            if lower not in _STOP_WORDS and lower not in seen:
                seen.add(lower)
                result.append(t)
        # A single stray long token can be a genuinely unusual word or a
        # pasted URL fragment; two or more is the pattern seen from a
        # whitespace-losing copy-paste, so that's the bar for warning the user.
        return result[:40], anomalies >= 2

    def _check_formatting(self, resume: ResumeOutputFormat) -> List[FormattingIssue]:
        issues: List[FormattingIssue] = []
        for i, exp in enumerate(resume.resume_section.experience):
            desc = exp.description or ""
            lines = [l.strip() for l in desc.split("\n") if l.strip()]
            bullet_lines = [l for l in lines if l.startswith(("-", "•", "*"))]

            if bullet_lines:
                first_words = {l.lstrip("-•* ").split()[0].lower() for l in bullet_lines if l.split()}
                if not first_words & ACTION_VERBS:
                    issues.append(FormattingIssue(i, "no_action_verbs"))

            for pattern, label in _VAGUE:
                if re.search(pattern, desc, re.IGNORECASE):
                    issues.append(FormattingIssue(i, "vague_language", label))
                    break

            if len(bullet_lines) < 2:
                issues.append(FormattingIssue(i, "few_bullets"))

        return issues
