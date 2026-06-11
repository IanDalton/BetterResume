"""Tests for the pydantic-ai ResumeAgent.

Uses TestModel/FunctionModel so no real API calls happen:
  - happy path: tools are exercised and structured output is returned
  - require_tool_call=True forces a retry when the model skips retrieval
  - require_tool_call=False allows direct answers
  - translation path never requires retrieval
  - legacy model-name normalization
"""

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from llm.agent import DEFAULT_MODEL, ResumeAgent, normalize_model_name
from models.resume import ResumeOutputFormat


class FakeDB:
    def get_job_experiences(self, user_id, type_filter=None):
        return [
            {"company": "Acme Corp", "end_date": "2024-01-01", "start_date": "2021-03-01"},
            {"company": "Beta Inc", "end_date": "2021-02-01", "start_date": "2018-06-01"},
        ]


# ---------------------------------------------------------------------------
# Model name normalization
# ---------------------------------------------------------------------------

def test_normalize_legacy_google_genai_prefix():
    assert normalize_model_name("google_genai:gemini-2.5-flash-lite") == "google-gla:gemini-2.5-flash-lite"


def test_normalize_bare_gemini_name():
    assert normalize_model_name("gemini-2.5-flash") == "google-gla:gemini-2.5-flash"


def test_normalize_passthrough_for_other_providers():
    assert normalize_model_name("openai:gpt-4o-mini") == "openai:gpt-4o-mini"
    assert normalize_model_name("anthropic:claude-haiku-4-5") == "anthropic:claude-haiku-4-5"


def test_normalize_none_returns_default():
    assert normalize_model_name(None) == DEFAULT_MODEL


def test_normalize_model_instance_passthrough():
    model = TestModel()
    assert normalize_model_name(model) is model


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

async def test_generate_returns_structured_resume(stub_vector_store, sample_resume_output):
    """TestModel calls every registered tool, then emits valid structured output."""
    model = TestModel(custom_output_args=sample_resume_output.model_dump())
    agent = ResumeAgent(model=model, vector_store=stub_vector_store, db=FakeDB())

    resume = await agent.generate("Senior Python engineer needed", user_id="u1")

    assert isinstance(resume, ResumeOutputFormat)
    assert resume.language == "en"
    # TestModel exercises all tools — the vector store must have been queried
    assert len(stub_vector_store.queries) >= 1


async def test_generate_forces_retrieval_when_model_skips_tools(stub_vector_store, sample_resume_output):
    """If the model answers without calling search_experience, the output validator
    must reject the answer (ModelRetry) and the model must succeed on retry."""
    resume_args = sample_resume_output.model_dump()
    calls = {"count": 0}

    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        calls["count"] += 1
        output_tool = next(t.name for t in info.output_tools)
        if calls["count"] == 1:
            # First attempt: skip retrieval, answer directly -> must be rejected
            return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args=resume_args)])
        if calls["count"] == 2:
            # Retry: do the retrieval this time
            return ModelResponse(parts=[ToolCallPart(tool_name="search_experience", args={"query": "python"})])
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args=resume_args)])

    agent = ResumeAgent(model=FunctionModel(model_fn), vector_store=stub_vector_store, db=FakeDB())
    resume = await agent.generate("Backend role", user_id="u1", require_tool_call=True)

    assert isinstance(resume, ResumeOutputFormat)
    assert calls["count"] == 3, "Model must be re-invoked after the rejected first answer"
    assert stub_vector_store.queries == ["python"]


async def test_generate_without_required_retrieval_allows_direct_answer(stub_vector_store, sample_resume_output):
    """require_tool_call=False must accept an answer with zero tool calls."""
    resume_args = sample_resume_output.model_dump()

    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        output_tool = next(t.name for t in info.output_tools)
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args=resume_args)])

    agent = ResumeAgent(model=FunctionModel(model_fn), vector_store=stub_vector_store, db=FakeDB())
    resume = await agent.generate("Backend role", user_id="u1", require_tool_call=False)

    assert isinstance(resume, ResumeOutputFormat)
    assert stub_vector_store.queries == []


async def test_search_tool_without_store_returns_empty(sample_resume_output):
    """The search tool degrades gracefully when no vector store is wired in."""
    model = TestModel(custom_output_args=sample_resume_output.model_dump())
    agent = ResumeAgent(model=model, vector_store=None, db=FakeDB())

    resume = await agent.generate("Some role", user_id="u1")
    assert isinstance(resume, ResumeOutputFormat)


async def test_latest_job_tool_uses_db(stub_vector_store, sample_resume_output):
    """get_latest_job_experience must read from the injected DB dependency."""
    seen = {}

    class RecordingDB(FakeDB):
        def get_job_experiences(self, user_id, type_filter=None):
            seen["user_id"] = user_id
            return super().get_job_experiences(user_id, type_filter)

    model = TestModel(custom_output_args=sample_resume_output.model_dump())
    agent = ResumeAgent(model=model, vector_store=stub_vector_store, db=RecordingDB())

    await agent.generate("Role", user_id="user_42")
    assert seen.get("user_id") == "user_42"


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

async def test_translate_returns_structured_resume(stub_vector_store, sample_resume_output):
    """Translation has no tools and must never require retrieval."""
    translated = sample_resume_output.model_dump()
    translated["language"] = "es"
    model = TestModel(custom_output_args=translated)
    agent = ResumeAgent(model=model, vector_store=stub_vector_store, db=FakeDB())

    result = await agent.translate(sample_resume_output, "Descripción del puesto", user_id="u1")

    assert isinstance(result, ResumeOutputFormat)
    assert result.language == "es"
    assert stub_vector_store.queries == []


async def test_prompts_are_loaded():
    agent = ResumeAgent(model=TestModel())
    assert "search_experience" in agent.JOB_PROMPT
    assert "translate" in agent.TRANSLATE_PROMPT.lower()
