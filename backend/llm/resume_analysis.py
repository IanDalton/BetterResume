"""User-facing resume analysis: an offline ATS score plus an LLM review with
improvement recommendations, combined into one response.

The ATS part reuses `evals.evaluators.ATSEvaluator` (deterministic, free) so
the number a user sees is the same one the admin eval dashboard reports. The
review part runs `llm.reviewer.review` on the judge model; when it fails the
ATS result is still returned, with `review_error` explaining the gap, because
a keyword scan with no recommendations beats an error page.
"""

import logging
from typing import List, Optional, Union

from pydantic import BaseModel, Field
from pydantic_ai.models import Model

from evals.evaluators.ats_evaluator import ATSEvaluator, IssueKind
from llm.reviewer import ResumeReview, review
from models.resume import ResumeOutputFormat

logger = logging.getLogger("betterresume.analysis")


class ATSIssue(BaseModel):
    experience_index: int
    kind: IssueKind
    detail: str = ""


class ATSAnalysis(BaseModel):
    score: int = Field(ge=0, le=100)
    keyword_coverage: int = Field(ge=0, le=100, description="Percent of job-description keywords found in the resume")
    matched_keywords: List[str]
    missing_keywords: List[str]
    issues: List[ATSIssue]


class ReviewScores(BaseModel):
    overall: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    quality: int = Field(ge=0, le=100)
    coherence: int = Field(ge=0, le=100)


class ReviewAnalysis(ResumeReview):
    """The reviewer's output with its 1-10 scores also exposed on the 0-100
    scale the UI shows next to the ATS score."""
    scores: ReviewScores


class ResumeAnalysis(BaseModel):
    ats: ATSAnalysis
    review: Optional[ReviewAnalysis] = None
    review_error: Optional[str] = None
    model: Optional[str] = Field(default=None, description="Model that produced the review, when one did")


def _pct(value: float) -> int:
    return max(0, min(100, int(round(value * 100))))


def ats_analysis(resume: ResumeOutputFormat, job_description: str) -> ATSAnalysis:
    result = ATSEvaluator().evaluate(resume, job_description)
    return ATSAnalysis(
        score=_pct(result.score),
        keyword_coverage=_pct(result.keyword_coverage),
        matched_keywords=result.matched_keywords,
        missing_keywords=result.missing_keywords,
        issues=[ATSIssue(experience_index=i.experience_index, kind=i.kind, detail=i.detail) for i in result.issues],
    )


def _with_scores(raw: ResumeReview) -> ReviewAnalysis:
    scores = ReviewScores(
        overall=_pct((raw.relevance + raw.quality + raw.coherence) / 30),
        relevance=_pct(raw.relevance / 10),
        quality=_pct(raw.quality / 10),
        coherence=_pct(raw.coherence / 10),
    )
    return ReviewAnalysis(**raw.model_dump(), scores=scores)


async def analyze_resume(
    resume: ResumeOutputFormat,
    job_description: str,
    *,
    language: Optional[str] = None,
    include_review: bool = True,
    model: Union[str, Model, None] = None,
) -> ResumeAnalysis:
    """`model` overrides the configured judge model (tests, CLI); production
    callers leave it unset so the admin dashboard stays the single place a
    model is chosen."""
    ats = ats_analysis(resume, job_description)
    if not include_review:
        return ResumeAnalysis(ats=ats)

    used = {"model": None}

    def _on_model_used(label: str, _fallback: bool) -> None:
        used["model"] = label

    try:
        raw = await review(
            resume, job_description,
            language=language,
            missing_keywords=ats.missing_keywords,
            formatting_issues=[
                f"experience[{i.experience_index}]: {i.kind}" + (f" ({i.detail})" if i.detail else "")
                for i in ats.issues
            ],
            model=model,
            on_model_used=_on_model_used,
        )
    except Exception as exc:
        logger.warning("Resume review failed; returning ATS analysis only: %s", exc, exc_info=True)
        return ResumeAnalysis(ats=ats, review_error=str(exc) or exc.__class__.__name__, model=used["model"])
    return ResumeAnalysis(ats=ats, review=_with_scores(raw), model=used["model"])
