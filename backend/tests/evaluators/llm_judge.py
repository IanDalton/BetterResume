import json
import logging
import os
from dataclasses import dataclass

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from models.resume import ResumeOutputFormat

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT = """\
You are an expert resume reviewer and hiring manager.
Evaluate the resume below against the provided job description.
Respond with ONLY a JSON object — no markdown, no explanation outside the JSON.

Score each dimension 1–10:
- relevance: how well the resume matches the job requirements
- quality: writing quality (action verbs, metrics, specificity, no vague adjectives)
- coherence: internal consistency (dates sensible, skills match claimed experience)

Required JSON format:
{
  "relevance": <1-10>,
  "quality": <1-10>,
  "coherence": <1-10>,
  "reasoning": "<2-3 sentences explaining your scores>"
}"""


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
            "JUDGE_MODEL", "google_genai:gemini-2.5-flash-lite"
        )
        provider, model_name = model_string.split(":", 1)
        self._llm = init_chat_model(model_name, model_provider=provider)

    def evaluate(self, resume: ResumeOutputFormat, job_description: str) -> LLMJudgeResult:
        resume_json = resume.model_dump_json(indent=2)
        user_msg = (
            f"JOB DESCRIPTION:\n{job_description}\n\n"
            f"RESUME JSON:\n{resume_json}\n\n"
            "Evaluate and respond with JSON only."
        )
        response = self._llm.invoke([
            SystemMessage(_JUDGE_SYSTEM_PROMPT),
            HumanMessage(user_msg),
        ])
        return self._parse(response.content)

    def _parse(self, raw: str) -> LLMJudgeResult:
        text = raw.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("LLM judge parse error: %s | raw: %.200s", e, raw)
            return LLMJudgeResult(0.0, 0.0, 0.0, 0.0, f"parse error: {e}")

        relevance = float(data.get("relevance", 5)) / 10
        quality = float(data.get("quality", 5)) / 10
        coherence = float(data.get("coherence", 5)) / 10
        overall = (relevance + quality + coherence) / 3

        return LLMJudgeResult(
            overall_score=round(overall, 3),
            relevance_score=round(relevance, 3),
            quality_score=round(quality, 3),
            coherence_score=round(coherence, 3),
            reasoning=data.get("reasoning", ""),
        )
