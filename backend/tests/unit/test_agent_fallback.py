"""Tests for OpenRouter provider routing and the two-layer model fallback.

Layer 1 — FallbackModel handles ModelAPIError (transport/provider 400s).
Layer 2 — an explicit UnexpectedModelBehavior catch handles output-retry
exhaustion, which is raised in pydantic_ai._agent_graph above the model layer
where FallbackModel cannot see it. This is the exact production failure:
"Exceeded maximum output retries (3)".
"""

from unittest.mock import patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from llm import agent, model_config


class FakeDB:
    def get_job_experiences(self, user_id, type_filter=None):
        return [{"company": "Acme Corp", "start_date": "2021-03-01", "end_date": "2024-01-01"}]


def _output_only_model(resume_args):
    """Answers immediately without calling search_experience."""
    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        output_tool = next(t.name for t in info.output_tools)
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args=resume_args)])
    return FunctionModel(model_fn)


def _retrieving_model(resume_args):
    """Calls search_experience once, then answers."""
    state = {"searched": False}

    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        output_tool = next(t.name for t in info.output_tools)
        if not state["searched"]:
            state["searched"] = True
            return ModelResponse(parts=[ToolCallPart(tool_name="search_experience", args={"queries": ["python", "sql"]})])
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args=resume_args)])

    return FunctionModel(model_fn)


def _raising_model(exc):
    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        raise exc
    return FunctionModel(model_fn)


def _searching_then_malformed_model():
    """Calls search_experience once (so deps.search_calls becomes 1), then
    always emits output args that fail schema validation -- simulating the
    reported production failure: a model that retrieves correctly but returns
    malformed tool-call arguments, burning all of its output retries."""
    state = {"searched": False}

    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        output_tool = next(t.name for t in info.output_tools)
        if not state["searched"]:
            state["searched"] = True
            return ModelResponse(parts=[ToolCallPart(tool_name="search_experience", args={"queries": ["python", "sql"]})])
        # Missing the required `resume_section` field -> pydantic-ai rejects
        # this and retries, eventually exhausting RETRIES.
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args={"language": "en"})])

    return FunctionModel(model_fn)


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------

def test_openrouter_settings_require_parameters():
    """Providers that cannot accept our tool-call params must be routed around."""
    settings = agent.model_settings_for("openrouter:qwen/qwen3-coder-30b-a3b-instruct")
    assert settings["openrouter_provider"]["require_parameters"] is True
    assert settings["openrouter_reasoning"] == {"enabled": False}


def test_non_openrouter_settings_untouched():
    assert agent.model_settings_for("google-gla:gemini-2.5-flash-lite") is None


# ---------------------------------------------------------------------------
# Layer 2: output-retry exhaustion (the reported production error)
# ---------------------------------------------------------------------------

async def test_falls_back_when_primary_exhausts_output_retries(stub_vector_store, sample_resume_output):
    resume_args = sample_resume_output.model_dump()
    seen = {}

    resume = await agent.generate(
        "Backend role",
        user_id="u1",
        vector_store=stub_vector_store,
        db=FakeDB(),
        model=_output_only_model(resume_args),          # never retrieves -> ModelRetry x3
        fallback_model=_retrieving_model(resume_args),  # retrieves -> succeeds
        require_tool_call=True,
        on_model_used=lambda name, fallback: seen.update(name=name, fallback=fallback),
    )

    assert resume.language == "en"
    assert seen["fallback"] is True


async def test_no_fallback_configured_propagates_original_error(stub_vector_store, sample_resume_output):
    with pytest.raises(UnexpectedModelBehavior, match="Exceeded maximum output retries"):
        await agent.generate(
            "Backend role",
            user_id="u1",
            vector_store=stub_vector_store,
            db=FakeDB(),
            model=_output_only_model(sample_resume_output.model_dump()),
            fallback_model=None,
            require_tool_call=True,
        )


async def test_failing_fallback_propagates_original_error(stub_vector_store, sample_resume_output):
    """When the fallback fails too, the caller sees the primary's failure."""
    with pytest.raises(UnexpectedModelBehavior, match="Exceeded maximum output retries"):
        await agent.generate(
            "Backend role",
            user_id="u1",
            vector_store=stub_vector_store,
            db=FakeDB(),
            model=_output_only_model(sample_resume_output.model_dump()),
            fallback_model=_output_only_model(sample_resume_output.model_dump()),
            require_tool_call=True,
        )


# ---------------------------------------------------------------------------
# Layer 1: transport / provider errors
# ---------------------------------------------------------------------------

async def test_falls_back_on_model_http_error(stub_vector_store, sample_resume_output):
    resume_args = sample_resume_output.model_dump()
    seen = {}

    resume = await agent.generate(
        "Backend role",
        user_id="u1",
        vector_store=stub_vector_store,
        db=FakeDB(),
        model=_raising_model(ModelHTTPError(status_code=400, model_name="bad", body="Provider returned error")),
        fallback_model=_retrieving_model(resume_args),
        require_tool_call=True,
        on_model_used=lambda name, fallback: seen.update(name=name, fallback=fallback),
    )

    assert resume.language == "en"
    assert seen["fallback"] is True


# ---------------------------------------------------------------------------
# Happy path reports no fallback
# ---------------------------------------------------------------------------

async def test_success_reports_primary_and_no_fallback(stub_vector_store, sample_resume_output):
    resume_args = sample_resume_output.model_dump()
    seen = {}

    await agent.generate(
        "Backend role",
        user_id="u1",
        vector_store=stub_vector_store,
        db=FakeDB(),
        model=_retrieving_model(resume_args),
        fallback_model=_retrieving_model(resume_args),
        require_tool_call=True,
        on_model_used=lambda name, fallback: seen.update(name=name, fallback=fallback),
    )

    assert seen["fallback"] is False


# ---------------------------------------------------------------------------
# Mixed-provider model settings (review finding: Layer 1's model_settings
# must reach an OpenRouter fallback even when the primary isn't OpenRouter)
# ---------------------------------------------------------------------------

def test_combined_settings_reach_openrouter_fallback_when_primary_is_not():
    settings = agent._combined_model_settings(
        "google-gla:gemini-2.5-flash-lite", "openrouter:qwen/qwen3-coder-30b-a3b-instruct"
    )
    assert settings["openrouter_provider"]["require_parameters"] is True
    assert settings["openrouter_reasoning"] == {"enabled": False}


def test_combined_settings_reach_openrouter_primary_when_fallback_is_not():
    settings = agent._combined_model_settings(
        "openrouter:qwen/qwen3-coder-30b-a3b-instruct", "google-gla:gemini-2.5-flash-lite"
    )
    assert settings["openrouter_provider"]["require_parameters"] is True


def test_combined_settings_none_when_neither_is_openrouter():
    assert agent._combined_model_settings("google-gla:a", "google-gla:b") is None


# ---------------------------------------------------------------------------
# Deps isolation between the primary and fallback runs (review finding: the
# Layer 2 retry must not inherit the primary's search_calls/tool_events, or
# the fallback's own retrieval-forcing validator is silently defeated)
# ---------------------------------------------------------------------------

async def test_fallback_retrieval_still_forced_after_primary_searched_and_failed(
    stub_vector_store, sample_resume_output
):
    """The primary calls search_experience, then emits malformed output args
    and exhausts its retries -- the same failure mode as
    `_output_only_model`, except this time the primary *did* retrieve first.
    The fallback (which never searches on its own) must still be forced to
    retrieve: if deps were reused as-is, the fallback would inherit
    search_calls=1 from the primary and `ensure_retrieval` would wrongly
    consider retrieval already satisfied, letting an ungrounded resume
    through instead of raising.
    """
    resume_args = sample_resume_output.model_dump()

    with pytest.raises(UnexpectedModelBehavior, match="Exceeded maximum output retries"):
        await agent.generate(
            "Backend role",
            user_id="u1",
            vector_store=stub_vector_store,
            db=FakeDB(),
            model=_searching_then_malformed_model(),
            fallback_model=_output_only_model(resume_args),
            require_tool_call=True,
        )


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

async def test_model_none_resolves_from_config(stub_vector_store, sample_resume_output):
    """model=None must consult model_config, not the DEFAULT_MODEL constant."""
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:configured/primary", "openrouter:configured/fallback"),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
        judge=model_config.TaskModels("openrouter:j", None),
    )
    with patch("llm.agent.get_model_config", return_value=cfg):
        primary, fallback = agent._resolve_model("generation", None)
    assert primary == "openrouter:configured/primary"
    assert fallback == "openrouter:configured/fallback"


def test_explicit_model_bypasses_config():
    with patch("llm.agent.get_model_config", side_effect=AssertionError("must not be consulted")):
        primary, fallback = agent._resolve_model("generation", "openrouter:explicit/x")
    assert primary == "openrouter:explicit/x"
    assert fallback is None


def test_explicit_legacy_model_is_normalized():
    """A caller (or a stored setting) still saying `google-gla:` must resolve to
    the provider pydantic-ai actually knows, not be passed through to fail."""
    with patch("llm.agent.get_model_config", side_effect=AssertionError("must not be consulted")):
        primary, fallback = agent._resolve_model("generation", "google-gla:gemini-2.5-flash-lite")
    assert primary == "google:gemini-2.5-flash-lite"
    assert fallback is None
