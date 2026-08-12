"""`search_experience` takes every concept in one call.

Regression cover for a production blowout: `qwen/qwen3.7-flash`, running with
an unforced tool choice, issued one search per model request and never got to
writing the resume -- 50 paid requests, then
`UsageLimitExceeded: The next request would exceed the request_limit of 50`.
One request per concept is what made that reachable at all.
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

import pytest
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from llm import agent
from llm.agent import MAX_SEARCH_QUERIES, REQUEST_LIMIT, ResumeDeps, search_experience


@dataclass
class RecordingStore:
    """Records each query it is asked for, and what it returned."""

    results: Optional[dict] = None
    calls: List[str] = field(default_factory=list)
    fail_on: Optional[str] = None

    async def aquery(self, query: str, user_id: str, n_results: int = 10) -> List[Tuple[str, float]]:
        self.calls.append(query)
        if self.fail_on == query:
            raise RuntimeError("embedding service down")
        if self.results is not None:
            return self.results.get(query, [])
        return [(f"doc for {query}", 0.9)]


class _Ctx:
    """Stands in for RunContext; the tool only reads `.deps`."""

    def __init__(self, deps):
        self.deps = deps


def _deps(store) -> ResumeDeps:
    return ResumeDeps(user_id="u1", vector_store=store, db=None, require_tool_call=True)


# ---------------------------------------------------------------------------
# One call, many queries
# ---------------------------------------------------------------------------

async def test_every_query_is_searched_and_grouped_by_query():
    store = RecordingStore()
    deps = _deps(store)

    out = await search_experience(_Ctx(deps), ["python", "sql", "dashboards"])

    assert store.calls == ["python", "sql", "dashboards"]
    assert list(out) == ["python", "sql", "dashboards"]
    assert out["sql"] == [("doc for sql", 0.9)]


async def test_a_batched_call_counts_as_one_tool_event_but_many_searches():
    """`ensure_retrieval` gates on `search_calls`, and the logs report effort --
    both should reflect concepts searched, not round trips."""
    deps = _deps(RecordingStore())

    await search_experience(_Ctx(deps), ["a", "b", "c"])

    assert deps.search_calls == 3
    assert deps.tool_events == [{"tool": "search_experience", "queries": ["a", "b", "c"]}]


async def test_a_bare_string_is_accepted_rather_than_bounced():
    """A model that sends the old single-query shape is answering the same
    question; coercing beats spending a request on a validation retry."""
    store = RecordingStore()
    deps = _deps(store)

    out = await search_experience(_Ctx(deps), "python")

    assert store.calls == ["python"]
    assert out == {"python": [("doc for python", 0.9)]}


async def test_a_json_encoded_array_is_parsed_into_its_queries():
    """Observed from qwen3.7-flash: it sends the list as a JSON *string*. Taken
    literally, the whole blob becomes one semantic query -- the verbose text the
    prompt warns retrieves poorly -- and it fails silently, returning
    plausible-looking matches for a garbage query."""
    store = RecordingStore()
    deps = _deps(store)

    out = await search_experience(_Ctx(deps), '["SQL data analysis", "Python pandas", "dashboards"]')

    assert store.calls == ["SQL data analysis", "Python pandas", "dashboards"]
    assert deps.search_calls == 3
    assert list(out) == ["SQL data analysis", "Python pandas", "dashboards"]


async def test_a_concept_that_merely_looks_like_json_is_still_searched():
    store = RecordingStore()
    out = await search_experience(_Ctx(_deps(store)), "[not json")
    assert store.calls == ["[not json"]
    assert list(out) == ["[not json"]


async def test_non_string_entries_are_dropped():
    store = RecordingStore()
    await search_experience(_Ctx(_deps(store)), ["python", None, 7, "sql"])
    assert store.calls == ["python", "sql"]


async def test_duplicate_documents_are_listed_once():
    """A small corpus returns the same document for several concepts; repeating
    it wastes the context the model has to write from."""
    shared = ("shared doc", 0.9)
    store = RecordingStore(results={"a": [shared], "b": [shared, ("only b", 0.7)]})
    deps = _deps(store)

    out = await search_experience(_Ctx(deps), ["a", "b"])

    assert out["a"] == [shared]
    assert out["b"] == [("only b", 0.7)]


async def test_one_failing_query_does_not_lose_the_others():
    store = RecordingStore(fail_on="b")
    deps = _deps(store)

    out = await search_experience(_Ctx(deps), ["a", "b", "c"])

    assert out["b"] == []
    assert out["a"] and out["c"]


async def test_blank_queries_are_dropped():
    store = RecordingStore()
    out = await search_experience(_Ctx(_deps(store)), ["  ", "python", ""])
    assert store.calls == ["python"]
    assert list(out) == ["python"]


async def test_an_empty_list_searches_nothing():
    store = RecordingStore()
    assert await search_experience(_Ctx(_deps(store)), []) == {}
    assert store.calls == []


async def test_query_count_is_capped():
    store = RecordingStore()
    await search_experience(_Ctx(_deps(store)), [f"q{i}" for i in range(MAX_SEARCH_QUERIES + 5)])
    assert len(store.calls) == MAX_SEARCH_QUERIES


async def test_missing_vector_store_returns_an_entry_per_query():
    deps = _deps(None)
    assert await search_experience(_Ctx(deps), ["a", "b"]) == {"a": [], "b": []}


# ---------------------------------------------------------------------------
# The run no longer costs 50 requests to fail
# ---------------------------------------------------------------------------

def _endless_searcher():
    """A model that searches forever without ever writing -- the observed
    behaviour of an unforced tool choice on qwen3.7-flash."""
    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(tool_name="search_experience", args={"queries": ["python"]})])

    return FunctionModel(model_fn)


async def test_a_model_that_never_finishes_is_cut_off_well_before_50_requests(stub_vector_store):
    with pytest.raises(UsageLimitExceeded) as excinfo:
        await agent.generate(
            "Backend role", user_id="u1", vector_store=stub_vector_store,
            model=_endless_searcher(), require_tool_call=True,
        )
    assert str(REQUEST_LIMIT) in str(excinfo.value)
    assert REQUEST_LIMIT < 50


async def test_a_model_that_never_finishes_falls_back(stub_vector_store, sample_resume_output):
    """The user gets a resume from the fallback instead of an error -- the
    runaway is raised above the model layer, so `FallbackModel` cannot see it
    and the explicit re-run has to catch it."""
    resume_args = sample_resume_output.model_dump()
    seen = {}

    def good(messages, info: AgentInfo) -> ModelResponse:
        output_tool = next(t.name for t in info.output_tools)
        if not any(isinstance(p, ToolCallPart) for m in messages for p in getattr(m, "parts", [])
                   if getattr(p, "tool_name", None) == "search_experience"):
            return ModelResponse(parts=[ToolCallPart(tool_name="search_experience", args={"queries": ["python"]})])
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args=resume_args)])

    resume = await agent.generate(
        "Backend role", user_id="u1", vector_store=stub_vector_store,
        model=_endless_searcher(), fallback_model=FunctionModel(good),
        require_tool_call=True,
        on_model_used=lambda name, fb: seen.update(name=name, fallback=fb),
    )

    assert resume.language == "en"
    assert seen["fallback"] is True
