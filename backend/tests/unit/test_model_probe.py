"""The dashboard checks a model before storing it.

Regression cover for a model that is tool-capable on paper but rejects the
forced tool call our agents always send (`openrouter:qwen/qwen3.7-flash`
404s with "No endpoints found that support the provided 'tool_choice' value").
Nothing in the OpenRouter catalog exposes that, so it has to be probed.
"""

import asyncio

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from llm import model_routing
from llm.model_probe import probe_model

TOOL_CHOICE_404 = ModelHTTPError(
    status_code=404,
    model_name="qwen/qwen3.7-flash",
    body={"message": "No endpoints found that support the provided 'tool_choice' value."},
)


def _answering_model():
    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        output_tool = next(t.name for t in info.output_tools)
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args={"answer": "ready"})])

    return FunctionModel(model_fn)


def _raising_model(exc):
    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        raise exc

    return FunctionModel(model_fn)


async def test_probe_passes_for_a_model_that_answers():
    result = await probe_model(_answering_model())
    assert result.ok is True


async def test_probe_reports_a_model_that_needs_an_unforced_tool_choice(monkeypatch):
    """The exact production failure. The model works once the tool choice is
    degraded, so the probe passes it -- and says so."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    model_routing.reset_known_models()

    def build(model_string, *, forced):
        return _raising_model(TOOL_CHOICE_404) if forced else _answering_model()

    monkeypatch.setattr(model_routing, "build_openrouter_model", build)
    result = await probe_model("openrouter:qwen/qwen3.7-flash")

    assert result.ok is True
    assert result.forced_tool_choice is False
    assert "forced tool choice" in result.message
    model_routing.reset_known_models()


async def test_probe_fails_a_model_that_fails_even_unforced():
    result = await probe_model(_raising_model(TOOL_CHOICE_404))
    assert result.ok is False
    assert "tool_choice" in result.detail


async def test_probe_sends_a_forced_tool_choice():
    """`tool_choice='required'` is what breaks incompatible models, so the probe
    is only meaningful if its request shape forces one -- i.e. output tools with
    no direct text output allowed."""
    seen = {}

    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        seen["allow_text"] = info.allow_text_output
        seen["output_tools"] = [t.name for t in info.output_tools]
        seen["function_tools"] = [t.name for t in info.function_tools]
        output_tool = next(t.name for t in info.output_tools)
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args={"answer": "ready"})])

    await probe_model(FunctionModel(model_fn))
    assert seen["allow_text"] is False
    assert seen["output_tools"]
    assert "probe_ping" in seen["function_tools"]


async def test_probe_times_out_instead_of_hanging():
    async def _never(*args, **kwargs):
        await asyncio.sleep(10)

    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        raise AssertionError("unreachable")

    slow = FunctionModel(model_fn)
    slow.request = _never  # type: ignore[method-assign]
    result = await probe_model(slow, timeout=0.05)
    assert result.ok is False
    assert "within" in result.detail


def test_probe_result_message_is_human_readable():
    from llm.model_probe import ProbeResult

    assert ProbeResult(True).message == "Model responded correctly"
    assert ProbeResult(False, "boom").message == "boom"
    assert ProbeResult(False).message


@pytest.mark.real_ai
async def test_probe_degrades_the_reported_model_for_real():
    """Live check against the model from the production report: it rejects a
    forced tool choice, and works once that is degraded."""
    model_routing.reset_known_models()
    try:
        result = await probe_model("openrouter:qwen/qwen3.7-flash")
    finally:
        model_routing.reset_known_models()
    assert result.ok is True
    assert result.forced_tool_choice is False
