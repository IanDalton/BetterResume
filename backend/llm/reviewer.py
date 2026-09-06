"""LLM resume reviewer: scores a generated resume against its job description
and produces concrete improvement recommendations for the user.

This is the user-facing counterpart of `evals.evaluators.llm_judge` (which
only produces scores for model comparison). It runs on the `judge` task model
configured in the admin dashboard -- the judge deliberately does not inherit
the generation model, so a resume is never graded by the model that wrote it.
"""

import logging
from typing import Callable, List, Literal, Optional, Sequence, Union

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from llm.agent import RETRIES, _log_usage, _resolve_model, _run_with_fallback
from models.resume import ResumeOutputFormat
from utils.file_io import load_prompt

logger = logging.getLogger("betterresume.reviewer")

REVIEW_PROMPT = load_prompt("review_prompt")

Section = Literal[
    "summary", "experience", "skills", "education", "languages", "keywords", "formatting", "general",
]
Severity = Literal["high", "medium", "low"]

# Human-readable names for the language codes the frontend UI uses. Anything
# else is passed through verbatim (the model copes with "pt" or "Portuguese").
_LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French", "de": "German", "it": "Italian"}


class Recommendation(BaseModel):
    section: Section = Field(description="Resume section the recommendation targets")
    severity: Severity = Field(description="high: likely costs the candidate the screen; low: polish")
    issue: str = Field(description="What is wrong or missing, concretely (quote the weak text when relevant)")
    suggestion: str = Field(description="What to change, concretely (a rewritten bullet, the keyword and where to put it, ...)")
    experience_index: Optional[int] = Field(
        default=None,
        description="Zero-based index into the resume's experience list when the recommendation is about one entry",
    )


class ResumeReview(BaseModel):
    relevance: int = Field(ge=1, le=10)
    quality: int = Field(ge=1, le=10)
    coherence: int = Field(ge=1, le=10)
    summary: str = Field(description="2-3 sentence overall verdict")
    strengths: List[str] = Field(default_factory=list, description="2-5 things the resume already does well for this job")
    recommendations: List[Recommendation] = Field(default_factory=list, description="3-8 improvements, most impactful first")
    keywords_to_add: List[str] = Field(
        default_factory=list,
        description="Job-description terms worth adding that the candidate can plausibly claim; at most 10",
    )


review_agent = Agent(
    output_type=ResumeReview,
    instructions=REVIEW_PROMPT,
    retries=RETRIES,
)


def _language_name(code: Optional[str], resume: ResumeOutputFormat) -> str:
    raw = (code or resume.language or "en").strip()
    return _LANGUAGE_NAMES.get(raw.lower(), raw)


def build_review_prompt(
    resume: ResumeOutputFormat,
    job_description: str,
    *,
    language: Optional[str] = None,
    missing_keywords: Sequence[str] = (),
    formatting_issues: Sequence[str] = (),
) -> str:
    missing = ", ".join(missing_keywords) if missing_keywords else "(none)"
    issues = "\n".join(f"- {issue}" for issue in formatting_issues) if formatting_issues else "- (none)"
    return (
        f"Write all text in: {_language_name(language, resume)}.\n\n"
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        f"RESUME JSON:\n{resume.model_dump_json(indent=2)}\n\n"
        f"ATS SCAN -- job description keywords missing from the resume:\n{missing}\n\n"
        f"ATS SCAN -- formatting findings:\n{issues}\n\n"
        "Review the resume."
    )


async def review(
    resume: ResumeOutputFormat,
    job_description: str,
    *,
    language: Optional[str] = None,
    missing_keywords: Sequence[str] = (),
    formatting_issues: Sequence[str] = (),
    model: Union[str, Model, None] = None,
    on_model_used: Optional[Callable[[str, bool], None]] = None,
) -> ResumeReview:
    """Review `resume` against `job_description` on the configured judge model.

    `language` is the code the recommendations should be written in (the UI
    language); it defaults to the resume's own language. The ATS scan results
    are passed along so the model can turn a raw missing-keyword list into the
    handful that actually matter for this job.
    """
    primary, fallback = _resolve_model("judge", model)
    prompt = build_review_prompt(
        resume, job_description,
        language=language, missing_keywords=missing_keywords, formatting_issues=formatting_issues,
    )
    logger.info("Review start language=%s model=%s", language or resume.language, primary)
    result = await _run_with_fallback(
        review_agent, prompt, primary=primary, fallback=fallback, on_model_used=on_model_used,
    )
    _log_usage("Review", result)
    return result.output
