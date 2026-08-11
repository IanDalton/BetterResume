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
import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, List, Optional, Tuple, Union

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.models import Model

from llm.model_config import get_model_config
from models.resume import ResumeOutputFormat
from utils.file_io import load_prompt
from utils.resume_import import (
    ResumeImportResult,
    entries_with_date_like_descriptions,
    strip_date_like_descriptions,
)

logger = logging.getLogger("betterresume.agent")

# Default model is configurable via the DEFAULT_MODEL env var (provider-prefixed,
# e.g. "openrouter:wafer/fp4" or "google:gemini-2.5-flash-lite").
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "openrouter:wafer/fp4")
RETRIES = 3

JOB_PROMPT = load_prompt("job_prompt")
TRANSLATION_PROMPT = load_prompt("translation_prompt")
RESUME_IMPORT_PROMPT = load_prompt("resume_import_prompt")

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


def _model_settings(model: Union[str, Model]) -> Optional[dict]:
    """Per-model run settings.

    For OpenRouter: disable reasoning tokens (latency), and set
    `require_parameters` so OpenRouter only routes to providers that accept the
    tool-call/structured-output parameters we send. Without it, requests get
    routed to providers that reject them outright (observed 400s from Alibaba,
    SiliconFlow, DigitalOcean) or return malformed tool arguments that burn all
    of the agent's output retries.

    Returns ``None`` for non-OpenRouter models so their defaults are untouched.
    """
    if isinstance(model, str):
        is_openrouter = model.startswith("openrouter:")
    else:
        is_openrouter = type(model).__name__ == "OpenRouterModel"
    if not is_openrouter:
        return None
    from pydantic_ai.models.openrouter import OpenRouterModelSettings

    return OpenRouterModelSettings(
        openrouter_reasoning={"enabled": False},
        openrouter_provider={"require_parameters": True},
    )


def _resolve_model(task: str, model: Union[str, Model, None]) -> Tuple[Union[str, Model], Optional[str]]:
    """Resolve (primary, fallback) for a task.

    An explicit `model` always wins and never gets a fallback here — that is
    what the eval runner and the tests pass, and they must exercise exactly
    the model they asked for. Callers may still supply their own
    `fallback_model` alongside an explicit `model`.
    """
    if model is not None:
        return normalize_model_name(model), None
    task_models = get_model_config().for_task(task)
    fallback = task_models.fallback
    return (
        normalize_model_name(task_models.primary),
        normalize_model_name(fallback) if fallback else None,
    )


def _model_label(model: Union[str, Model]) -> str:
    return model if isinstance(model, str) else getattr(model, "model_name", type(model).__name__)


def _combined_model_settings(primary: Union[str, Model], fallback: Union[str, Model, None]) -> Optional[dict]:
    """Model settings for a single `FallbackModel` run.

    `FallbackModel` sends the same `model_settings` to whichever sub-model
    handles the request, so settings computed from `primary` alone are wrong
    the moment the primary fails and OpenRouter's `require_parameters` needs
    to reach an OpenRouter *fallback* instead (or vice versa). Provider-
    namespaced keys (e.g. `openrouter_*`) are ignored by other providers, so
    merging both sub-models' settings is safe in either direction.
    """
    if fallback is None:
        return _model_settings(primary)
    return {**(_model_settings(primary) or {}), **(_model_settings(fallback) or {})} or None


def _reset_retry_deps(deps: Any) -> None:
    """Give the Layer 2 fallback re-run a clean slate.

    The re-run is a brand new conversation against a different model, reusing
    the same `deps` object (it arrives via `**run_kwargs`). If it still carries
    mutable state from the primary's failed conversation -- e.g.
    `ResumeDeps.search_calls` / `tool_events` -- the fallback's own
    `ensure_retrieval` output validator would see a nonzero `search_calls` and
    conclude retrieval already happened, silently letting the fallback answer
    ungrounded. Reset in place (not a fresh object) so identity-based callers
    (e.g. the `searches=%d` log in `generate`) still see accurate counts.
    """
    if hasattr(deps, "search_calls"):
        deps.search_calls = 0
    if hasattr(deps, "tool_events"):
        deps.tool_events = []


async def _run_with_fallback(
    agent_obj: Agent,
    prompt: Any,
    *,
    primary: Union[str, Model],
    fallback: Union[str, Model, None],
    on_model_used: Optional[Callable[[str, bool], None]] = None,
    **run_kwargs,
):
    """Run `agent_obj` on `primary`, falling back to `fallback` on failure.

    Two distinct failure modes need two mechanisms:

    1. Transport/provider errors (`ModelAPIError`, which `ModelHTTPError`
       subclasses) are handled by `FallbackModel`, inside the model layer.
    2. Output-retry exhaustion raises `UnexpectedModelBehavior` from
       `pydantic_ai._agent_graph`, *above* the model layer, where FallbackModel
       never sees it. That needs the explicit re-run below.
    """
    def _report(label: str, used_fallback: bool) -> None:
        if on_model_used:
            on_model_used(label, used_fallback)

    if fallback is None:
        result = await agent_obj.run(prompt, model=primary, model_settings=_model_settings(primary), **run_kwargs)
        _report(_model_label(primary), False)
        return result

    from pydantic_ai.models.fallback import FallbackModel
    from pydantic_ai.models.wrapper import WrapperModel

    # `FallbackModel` doesn't expose which of its sub-models actually answered
    # in a way we can trust: the response's `model_name` is set by the model
    # implementation itself, and test doubles (and, in principle, real models
    # sharing a name) can collide. Wrap each sub-model so it marks itself when
    # its `request()` completes successfully -- an identity check, not a
    # string comparison -- so we know for certain which one served the run.
    primary_marker = {"used": False}
    fallback_marker = {"used": False}

    class _TrackingModel(WrapperModel):
        def __init__(self, wrapped: Union[str, Model], marker: dict):
            super().__init__(wrapped)
            self._marker = marker

        async def request(self, messages, model_settings, model_request_parameters):
            response = await self.wrapped.request(messages, model_settings, model_request_parameters)
            self._marker["used"] = True
            return response

    layered = FallbackModel(
        _TrackingModel(primary, primary_marker),
        _TrackingModel(fallback, fallback_marker),
        fallback_on=(ModelAPIError,),
    )
    try:
        result = await agent_obj.run(
            prompt, model=layered, model_settings=_combined_model_settings(primary, fallback), **run_kwargs
        )
    except UnexpectedModelBehavior as exc:
        logger.warning(
            "Primary model %s failed output validation (%s); retrying on fallback %s",
            _model_label(primary), exc, _model_label(fallback),
        )
        deps_obj = run_kwargs.get("deps")
        if deps_obj is not None:
            _reset_retry_deps(deps_obj)
        try:
            result = await agent_obj.run(
                prompt, model=fallback, model_settings=_model_settings(fallback), **run_kwargs
            )
        except Exception:
            logger.warning("Fallback model %s also failed; surfacing the primary error", _model_label(fallback))
            raise exc
        _report(_model_label(fallback), True)
        return result

    used_fallback = fallback_marker["used"]
    label = _model_label(fallback) if used_fallback else _model_label(primary)
    if used_fallback:
        logger.warning("Primary model %s unavailable; served by fallback %s", _model_label(primary), label)
    _report(label, used_fallback)
    return result


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

# No tools/deps needed: pure text-in, structured-out extraction.
resume_import_agent = Agent(
    output_type=ResumeImportResult,
    instructions=RESUME_IMPORT_PROMPT,
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

    This is a meaning-based search, so query phrasing determines what is retrieved.

    Args:
        query: A short, generalized, single-concept phrase (about 2-6 words)
            describing one skill, responsibility, or domain to look for, e.g.
            "REST API development" or "team leadership". Do not paste full
            sentences or verbatim job-description requirements — verbose,
            hyper-specific text retrieves poorly. Use separate calls for
            related terms instead of combining them.
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
            "before writing the resume. Call it now, using short, generalized, "
            "single-concept queries (about 2-6 words each) derived from the job "
            "description — not full sentences or verbatim requirement lines."
        )
    return output


@resume_import_agent.output_validator
async def ensure_real_descriptions(ctx: RunContext[None], output: ResumeImportResult) -> ResumeImportResult:
    """Reject extractions where a description is just the entry's date-range/
    duration line (a failure mode of smaller models -- the real bullets are in
    the source text but the model copied the date line near the role title
    instead). After the retries are spent, degrade gracefully: strip the
    date-like lines and warn rather than failing the whole import."""
    offenders = entries_with_date_like_descriptions(output)
    if not offenders:
        return output
    if ctx.retry < RETRIES - 1:
        labels = "; ".join(f"{e.role or '?'} at {e.company}" for e in offenders)
        logger.info("Resume import rejected: date-like descriptions for %s (retry %d)", labels, ctx.retry)
        raise ModelRetry(
            "The `description` of these entries is the date range/duration line, which is wrong: "
            f"{labels}. A description must be ONLY the descriptive bullet/summary text of the entry "
            "in the source, copied verbatim. Dates go only in start_date/end_date; durations are "
            "discarded. If an entry has no descriptive text in the source, set description to an "
            "empty string -- never the dates."
        )
    logger.warning("Resume import: stripping date-like descriptions after retries for %d entries", len(offenders))
    return strip_date_like_descriptions(output)


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
    fallback_model: Union[str, Model, None] = None,
    require_tool_call: bool = True,
    extra_context: Optional[str] = None,
    on_model_used: Optional[Callable[[str, bool], None]] = None,
) -> ResumeOutputFormat:
    """Generate a structured resume for a job description.

    Args:
        model: explicit model; when None, resolved from runtime configuration.
        fallback_model: explicit fallback; when None and `model` is None, the
            configured fallback for the generation task is used.
        extra_context: Authoritative facts (current date, computed years of
            experience, spoken languages) appended to the prompt so the model
            stays consistent with the user's stored data.
        on_model_used: called with (model_string, fallback_used) once the run
            succeeds, so callers can record what actually served the request.
    """
    primary, configured_fallback = _resolve_model("generation", model)
    fallback = normalize_model_name(fallback_model) if fallback_model is not None else configured_fallback
    deps = ResumeDeps(
        user_id=user_id,
        vector_store=vector_store,
        db=db,
        require_tool_call=require_tool_call,
    )
    start = time.monotonic()
    logger.info("Generation start user=%s model=%s fallback=%s jd_chars=%d",
                user_id, primary, fallback, len(jd or ""))
    prompt = jd if not extra_context else f"{jd}\n\n{extra_context}"
    result = await _run_with_fallback(
        generation_agent, prompt,
        primary=primary, fallback=fallback, on_model_used=on_model_used, deps=deps,
    )
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
    fallback_model: Union[str, Model, None] = None,
    on_model_used: Optional[Callable[[str, bool], None]] = None,
) -> ResumeOutputFormat:
    """Translate a structured resume into the language of the original job description."""
    primary, configured_fallback = _resolve_model("translation", model)
    fallback = normalize_model_name(fallback_model) if fallback_model is not None else configured_fallback
    prompt = (
        f"ORIGINAL JOB DESCRIPTION:\n{original_jd}\n\n"
        f"RESUME JSON:\n{resume.model_dump_json()}"
    )
    logger.info("Translation start user=%s language=%s model=%s fallback=%s",
                user_id, resume.language, primary, fallback)
    result = await _run_with_fallback(
        translation_agent, prompt,
        primary=primary, fallback=fallback, on_model_used=on_model_used,
    )
    _log_usage("Translation", result)
    return result.output


async def extract_resume_fields(
    text: str,
    *,
    model: Union[str, Model, None] = None,
    fallback_model: Union[str, Model, None] = None,
    on_model_used: Optional[Callable[[str, bool], None]] = None,
) -> ResumeImportResult:
    """Structured extraction of profile/experience/education/language data
    from a resume PDF's cleaned text (see utils/resume_import.py)."""
    primary, configured_fallback = _resolve_model("import", model)
    fallback = normalize_model_name(fallback_model) if fallback_model is not None else configured_fallback
    logger.info("Resume import extraction start; chars=%d model=%s fallback=%s", len(text or ""), primary, fallback)
    result = await _run_with_fallback(
        resume_import_agent, text,
        primary=primary, fallback=fallback, on_model_used=on_model_used,
    )
    _log_usage("Resume import extraction", result)
    return result.output
