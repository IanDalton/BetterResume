"""Models that reject a forced tool choice are retried unforced, not failed.

`openrouter:qwen/qwen3.7-flash` 404s on every request our agents make
("No endpoints found that support the provided 'tool_choice' value") because its
only endpoint accepts `tool_choice: "auto"`. It answers fine when asked rather
than forced, so the model layer degrades instead of surfacing the error.
"""

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from llm import model_routing


class _Answer(BaseModel):
    answer: str


# Same shape as the real agents: structured output and a function tool, so
# pydantic-ai asks for a forced tool call.
agent_under_test = Agent(output_type=_Answer, retries=0)


@agent_under_test.tool_plain
def ping() -> str:
    """Give the agent a function tool."""
    return "pong"


TOOL_CHOICE_404 = ModelHTTPError(
    status_code=404,
    model_name="qwen/qwen3.7-flash",
    body={"message": "No endpoints found that support the provided 'tool_choice' value."},
)


@pytest.fixture(autouse=True)
def _forget_learned_models():
    model_routing.reset_known_models()
    yield
    model_routing.reset_known_models()


def _builder(calls: list):
    """Stands in for the real OpenRouter model builder: records how each model
    was built and rejects forced requests, like the reported model does."""

    def build(model_string: str, *, forced: bool):
        calls.append(forced)

        def model_fn(messages, info: AgentInfo) -> ModelResponse:
            if forced:
                raise TOOL_CHOICE_404
            output_tool = next(t.name for t in info.output_tools)
            return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args={"answer": "ready"})])

        return FunctionModel(model_fn)

    return build


# ---------------------------------------------------------------------------
# Error recognition
# ---------------------------------------------------------------------------

def test_recognizes_the_openrouter_rejection():
    assert model_routing.is_tool_forcing_rejection(TOOL_CHOICE_404)


def test_recognizes_a_provider_level_rejection():
    exc = ModelHTTPError(status_code=400, model_name="m", body={"error": "unsupported tool_choice value"})
    assert model_routing.is_tool_forcing_rejection(exc)


def test_other_errors_are_not_mistaken_for_it():
    assert not model_routing.is_tool_forcing_rejection(
        ModelHTTPError(status_code=429, model_name="m", body="rate limited")
    )
    assert not model_routing.is_tool_forcing_rejection(RuntimeError("boom"))


# ---------------------------------------------------------------------------
# Degrade and remember
# ---------------------------------------------------------------------------

async def test_rejected_forcing_is_retried_unforced():
    calls: list = []
    model = model_routing.AdaptiveRoutingModel("openrouter:qwen/qwen3.7-flash", builder=_builder(calls))

    result = await agent_under_test.run("Say ready.", model=model)

    assert result.output.answer == "ready"
    assert calls == [True, False]  # forced first, then degraded


async def test_the_degrade_is_remembered_for_later_runs():
    calls: list = []
    build = _builder(calls)

    await agent_under_test.run(
        "Say ready.", model=model_routing.AdaptiveRoutingModel("openrouter:qwen/qwen3.7-flash", builder=build)
    )
    calls.clear()
    await agent_under_test.run(
        "Say ready.", model=model_routing.AdaptiveRoutingModel("openrouter:qwen/qwen3.7-flash", builder=build)
    )

    # Second run never pays for the discovery again.
    assert calls == [False]
    assert model_routing.concessions_for("openrouter:qwen/qwen3.7-flash").unforced_tool_choice


async def test_a_different_model_is_unaffected():
    model_routing.remember("openrouter:qwen/qwen3.7-flash", unforced_tool_choice=True)
    assert not model_routing.concessions_for("openrouter:google/gemini-2.5-flash-lite").unforced_tool_choice


async def test_unrelated_errors_still_surface():
    rate_limited = ModelHTTPError(status_code=429, model_name="m", body="rate limited")

    def build(model_string, *, forced):
        def model_fn(messages, info: AgentInfo) -> ModelResponse:
            raise rate_limited

        return FunctionModel(model_fn)

    model = model_routing.AdaptiveRoutingModel("openrouter:x/y", builder=build)
    with pytest.raises(ModelHTTPError, match="rate limited"):
        await agent_under_test.run("Say ready.", model=model)
    assert not model_routing.concessions_for("openrouter:x/y").unforced_tool_choice


# ---------------------------------------------------------------------------
# Reasoning: the same treatment, a different demand
#
# `reasoning={"enabled": false}` under `require_parameters` disqualifies every
# endpoint of a model that takes no reasoning parameter (83 of OpenRouter's 333
# tool-capable models) and is refused outright by models that mandate it.
# ---------------------------------------------------------------------------

REASONING_MANDATORY = ModelHTTPError(
    status_code=400, model_name="openai/gpt-5-nano",
    body={"message": "Reasoning is mandatory for this endpoint and cannot be disabled."},
)
NO_ENDPOINTS_FOR_PARAMS = ModelHTTPError(
    status_code=404, model_name="qwen/qwen3-coder-30b-a3b-instruct",
    body={"message": "No endpoints found that can handle the requested parameters."},
)

REASONING_OFF = {"openrouter_reasoning": {"enabled": False},
                 "openrouter_provider": {"require_parameters": True}}


def _reasoning_sensitive_model(error, seen: list):
    """Fails while `openrouter_reasoning` is present, like the real endpoints."""

    def build(model_string, *, forced):
        def model_fn(messages, info: AgentInfo) -> ModelResponse:
            seen.append(dict(info.model_settings or {}))
            if "openrouter_reasoning" in (info.model_settings or {}):
                raise error
            output_tool = next(t.name for t in info.output_tools)
            return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args={"answer": "ready"})])

        return FunctionModel(model_fn)

    return build


@pytest.mark.parametrize("error", [REASONING_MANDATORY, NO_ENDPOINTS_FOR_PARAMS])
async def test_reasoning_disable_is_dropped_when_refused(error):
    seen: list = []
    model = model_routing.AdaptiveRoutingModel("openrouter:x/y", builder=_reasoning_sensitive_model(error, seen))

    result = await agent_under_test.run("Say ready.", model=model, model_settings=dict(REASONING_OFF))

    assert result.output.answer == "ready"
    assert model_routing.concessions_for("openrouter:x/y").allow_reasoning
    # First attempt disables reasoning, retry drops that but keeps the routing
    # constraint that makes our tool parameters mandatory.
    assert "openrouter_reasoning" in seen[0]
    assert "openrouter_reasoning" not in seen[1]
    assert seen[1]["openrouter_provider"] == {"require_parameters": True}


async def test_a_model_needing_both_concessions_gets_both():
    attempts: list = []

    def build(model_string, *, forced):
        def model_fn(messages, info: AgentInfo) -> ModelResponse:
            settings = dict(info.model_settings or {})
            attempts.append((forced, "openrouter_reasoning" in settings))
            if forced:
                raise TOOL_CHOICE_404
            if "openrouter_reasoning" in settings:
                raise NO_ENDPOINTS_FOR_PARAMS
            output_tool = next(t.name for t in info.output_tools)
            return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args={"answer": "ready"})])

        return FunctionModel(model_fn)

    model = model_routing.AdaptiveRoutingModel("openrouter:x/y", builder=build)
    result = await agent_under_test.run("Say ready.", model=model, model_settings=dict(REASONING_OFF))

    assert result.output.answer == "ready"
    assert attempts == [(True, True), (False, True), (False, False)]
    learned = model_routing.concessions_for("openrouter:x/y")
    assert learned.unforced_tool_choice and learned.allow_reasoning


def test_concessions_describe_themselves_for_the_dashboard():
    both = model_routing.Concessions(unforced_tool_choice=True, allow_reasoning=True)
    assert "forced tool choice" in both.describe()
    assert "reasoning" in both.describe()
    assert not model_routing.Concessions()


# ---------------------------------------------------------------------------
# What gets wrapped
# ---------------------------------------------------------------------------

def test_openrouter_strings_are_wrapped(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    prepared = model_routing.prepare("openrouter:google/gemini-2.5-flash-lite")
    assert isinstance(prepared, model_routing.AdaptiveRoutingModel)


def test_other_providers_are_left_alone():
    assert model_routing.prepare("google:gemini-2.5-flash-lite") == "google:gemini-2.5-flash-lite"


def test_model_instances_are_left_alone():
    """The eval runner and the tests pass `Model` objects; they must reach
    pydantic-ai untouched."""
    model = TestModel()
    assert model_routing.prepare(model) is model


def test_none_is_left_alone():
    assert model_routing.prepare(None) is None
