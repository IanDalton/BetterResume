"""pydantic-ai agents for resume generation and translation.

Follows pydantic-ai best practices: the two `Agent`s are module-level
singletons (like a FastAPI app), tools and validators are registered with
module-level decorators, and all per-run state travels in `ResumeDeps`.
No model is bound at construction time — callers pass one to `generate` /
`translate` (defaulting to `DEFAULT_MODEL`), so importing this module never
requires provider credentials.

Tool-call forcing (the old `tool_choice="any"`) is implemented with an
output validator: if retrieval was required but never happened, the model is
asked to retry and call `search_experience` first.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, List, Optional, Tuple, Union

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from models.resume import ResumeOutputFormat
from utils.file_io import load_prompt

logger = logging.getLogger("betterresume.agent")

DEFAULT_MODEL = "google:gemini-2.5-flash-lite"
RETRIES = 3

JOB_PROMPT = load_prompt("job_prompt")
TRANSLATION_PROMPT = load_prompt("translation_prompt")

# Older code/config used LangChain provider prefixes; map them onto pydantic-ai ones.
_LEGACY_PROVIDER_MAP = {
    "google_genai": "google",
    "gemini": "google",
    "google": "google",
    "google-gla": "google-gla",
}


def normalize_model_name(model: Union[str, Model, None]) -> Union[str, Model]:
    """Translate legacy provider prefixes (e.g. ``google_genai:``) to pydantic-ai names."""
    if model is None:
        return DEFAULT_MODEL
    if not isinstance(model, str):
        return model
    if ":" in model:
        provider, name = model.split(":", 1)
        provider = _LEGACY_PROVIDER_MAP.get(provider, provider)
        return f"{provider}:{name}"
    # Bare Gemini model names default to the Google provider
    if model.startswith("gemini"):
        return f"google:{model}"
    return model


@dataclass
class ResumeDeps:
    """Per-run dependencies handed to the agent tools."""

    user_id: str
    vector_store: Any = None
    db: Any = None
    require_tool_call: bool = False
    search_calls: int = 0
    tool_events: List[dict] = field(default_factory=list)


generation_agent = Agent(
    deps_type=ResumeDeps,
    output_type=ResumeOutputFormat,
    instructions=JOB_PROMPT,
    retries=RETRIES,
)

translation_agent = Agent(
    output_type=ResumeOutputFormat,
    instructions=TRANSLATION_PROMPT,
    retries=RETRIES,
)


@generation_agent.instructions
def current_date_instructions(ctx: RunContext[ResumeDeps]) -> str:
    today = date.today().strftime("%m/%Y")
    return (
        f"Today's date is {today}. A resume documents experience already acquired: "
        f"never output a start or end date later than {today}, and label ongoing roles "
        "with 'Present' as the end date. Copy dates exactly from the retrieved data; "
        "never invent or shift them."
    )


@generation_agent.tool
async def search_experience(ctx: RunContext[ResumeDeps], query: str, n_results: int = 10) -> List[Tuple[str, float]]:
    """Semantic search over the user's stored experience, skills, education and projects.

    Args:
        query: Free-text query describing the skill/responsibility to look for.
        n_results: Maximum number of matching documents to return.
    """
    ctx.deps.search_calls += 1
    ctx.deps.tool_events.append({"tool": "search_experience", "query": query})
    store = ctx.deps.vector_store
    if store is None:
        logger.warning("search_experience called without a vector store user=%s", ctx.deps.user_id)
        return []
    results = await store.aquery(query, ctx.deps.user_id, n_results=n_results)
    logger.info(
        "search_experience user=%s query=%r results=%s",
        ctx.deps.user_id, query, len(results) if isinstance(results, list) else results,
    )
    return results


@generation_agent.tool
async def get_latest_job_experience(ctx: RunContext[ResumeDeps]) -> Any:
    """Get the user's most recent job experience to anchor the resume timeline."""
    ctx.deps.tool_events.append({"tool": "get_latest_job_experience"})
    uid = ctx.deps.user_id
    if not uid:
        return "User ID not provided."

    db = ctx.deps.db
    if db is None:
        from utils.db_storage import DBStorage
        db = DBStorage()

    experiences = await asyncio.to_thread(db.get_job_experiences, uid)
    if not experiences:
        return "No job experiences found."

    def get_date(exp):
        return exp.get("end_date") or exp.get("start_date") or ""

    latest = sorted(experiences, key=get_date, reverse=True)[0]
    logger.info("get_latest_job_experience user=%s company=%s", uid, latest.get("company"))
    return latest


@generation_agent.output_validator
async def ensure_retrieval(ctx: RunContext[ResumeDeps], output: ResumeOutputFormat) -> ResumeOutputFormat:
    if ctx.deps.require_tool_call and ctx.deps.search_calls == 0:
        logger.info("Output rejected: retrieval required but search_experience was never called")
        raise ModelRetry(
            "You must call search_experience to retrieve the user's stored experience "
            "before writing the resume. Call it now with queries derived from the job description."
        )
    return output


def _log_usage(label: str, result) -> None:
    try:
        usage = result.usage
        logger.info(
            "%s complete; input_tokens=%s output_tokens=%s requests=%s",
            label,
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
            getattr(usage, "requests", None),
        )
    except Exception:
        logger.debug("%s complete; usage unavailable", label)


async def generate(
    jd: str,
    *,
    user_id: str,
    vector_store: Any = None,
    db: Any = None,
    model: Union[str, Model, None] = None,
    require_tool_call: bool = True,
    extra_context: Optional[str] = None,
) -> ResumeOutputFormat:
    """Generate a structured resume for a job description.

    Args:
        extra_context: Authoritative facts (current date, computed years of
            experience, spoken languages) appended to the prompt so the model
            stays consistent with the user's stored data.
    """
    model = normalize_model_name(model)
    deps = ResumeDeps(
        user_id=user_id,
        vector_store=vector_store,
        db=db,
        require_tool_call=require_tool_call,
    )
    start = time.monotonic()
    logger.info("Generation start user=%s model=%s jd_chars=%d", user_id, model, len(jd or ""))
    prompt = jd if not extra_context else f"{jd}\n\n{extra_context}"
    result = await generation_agent.run(prompt, model=model, deps=deps)
    logger.info(
        "Generation finished user=%s in %dms; searches=%d",
        user_id, int((time.monotonic() - start) * 1000), deps.search_calls,
    )
    _log_usage("Generation", result)
    return result.output


async def translate(
    resume: ResumeOutputFormat,
    original_jd: str,
    *,
    user_id: str,
    model: Union[str, Model, None] = None,
) -> ResumeOutputFormat:
    """Translate a structured resume into the language of the original job description."""
    model = normalize_model_name(model)
    prompt = (
        f"ORIGINAL JOB DESCRIPTION:\n{original_jd}\n\n"
        f"RESUME JSON:\n{resume.model_dump_json()}"
    )
    logger.info("Translation start user=%s language=%s", user_id, resume.language)
    result = await translation_agent.run(prompt, model=model)
    _log_usage("Translation", result)
    return result.output
