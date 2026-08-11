import logging
import os
from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from llm.agent import normalize_model_name
from models.resume import ResumeOutputFormat

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """\
You are an expert resume reviewer and hiring manager.
Evaluate the resume below against the provided job description.

Score each dimension 1–10:
- relevance: how well the resume matches the job requirements
- quality: writing quality (action verbs, metrics, specificity, no vague adjectives)
- coherence: internal consistency (dates sensible, skills match claimed experience)
"""


class _JudgeScores(BaseModel):
    relevance: int = Field(ge=1, le=10)
    quality: int = Field(ge=1, le=10)
    coherence: int = Field(ge=1, le=10)
    reasoning: str = Field(description="2-3 sentences explaining the scores")


@dataclass
class LLMJudgeResult:
    overall_score: float
    relevance_score: float
    quality_score: float
    coherence_score: float
    reasoning: str


class LLMJudge:
    """LLM-as-judge evaluator. Requires a real API key. Only used in integration tests."""

    def __init__(self, judge_model: str = None):
        model_string = judge_model or os.getenv(
            "JUDGE_MODEL", "google-gla:gemini-2.5-flash-lite"
        )
        self._agent = Agent(
            normalize_model_name(model_string),
            output_type=_JudgeScores,
            instructions=_JUDGE_SYSTEM_PROMPT,
        )

    def evaluate(self, resume: ResumeOutputFormat, job_description: str) -> LLMJudgeResult:
        result = self._agent.run_sync(self._user_message(resume, job_description))
        return self._from_scores(result.output)

    async def aevaluate(self, resume: ResumeOutputFormat, job_description: str) -> LLMJudgeResult:
        """Async variant. Required by the API-triggered runner: `run_sync` raises
        when called from inside a running event loop."""
        result = await self._agent.run(self._user_message(resume, job_description))
        return self._from_scores(result.output)

    @staticmethod
    def _user_message(resume: ResumeOutputFormat, job_description: str) -> str:
        return (
            f"JOB DESCRIPTION:\n{job_description}\n\n"
            f"RESUME JSON:\n{resume.model_dump_json(indent=2)}\n\n"
            "Evaluate the resume."
        )

    @staticmethod
    def _from_scores(scores: _JudgeScores) -> LLMJudgeResult:
        relevance = scores.relevance / 10
        quality = scores.quality / 10
        coherence = scores.coherence / 10
        overall = (relevance + quality + coherence) / 3
        return LLMJudgeResult(
            overall_score=round(overall, 3),
            relevance_score=round(relevance, 3),
            quality_score=round(quality, 3),
            coherence_score=round(coherence, 3),
            reasoning=scores.reasoning,
        )
