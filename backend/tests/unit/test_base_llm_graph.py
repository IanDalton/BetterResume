"""Tests for the custom LangGraph agent in BaseLLM.

Verifies that:
  - When require_tool_call=True and no tool results are present, the model is
    called with tool_choice="any" (forced), not with optional tool binding.
  - When tool results already exist, the optional binding is used.
  - Translation invocations (require_tool_call absent) never use the forced binding.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage


def _ai_msg():
    """AIMessage with no tool_calls — signals end of the ReAct loop."""
    msg = AIMessage(content="resume output")
    msg.tool_calls = []
    return msg


def _build_agent(mock_chat, mock_tool):
    """Construct a GeminiAgent with a mocked chat model and a single tool."""
    with patch("llm.base.init_chat_model", return_value=mock_chat), \
         patch("llm.base.ToolNode", return_value=MagicMock()):
        from llm.gemini_agent import GeminiAgent
        return GeminiAgent(tools=[mock_tool], output_format=MagicMock())


# ---------------------------------------------------------------------------
# Tests: verify that the call_agent node selects the right model binding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forced_tool_call_used_on_first_invocation():
    """When require_tool_call=True and no ToolMessages exist, model_forced_tools.ainvoke is called."""
    forced_calls: list = []
    optional_calls: list = []

    # Separate mock objects so we can track which one was called
    forced_model = MagicMock()
    forced_model.ainvoke = AsyncMock(side_effect=lambda msgs: (forced_calls.append(1) or _ai_msg()))

    optional_model = MagicMock()
    optional_model.ainvoke = AsyncMock(side_effect=lambda msgs: (optional_calls.append(1) or _ai_msg()))

    structured_model = MagicMock()
    structured_model.ainvoke = AsyncMock(return_value=MagicMock())

    mock_chat = MagicMock()
    mock_chat.bind_tools.side_effect = lambda tools, **kw: (
        forced_model if kw.get("tool_choice") == "any" else optional_model
    )
    mock_chat.with_structured_output.return_value = structured_model

    mock_tool = MagicMock()
    mock_tool.name = "MockTool"

    agent = _build_agent(mock_chat, mock_tool)

    await agent.ainvoke({
        "messages": [SystemMessage("system"), HumanMessage("job desc")],
        "user_id": "u1",
        "require_tool_call": True,
    })

    assert len(forced_calls) == 1, "Forced model must be called exactly once on first pass"
    assert len(optional_calls) == 0, "Optional model must not be called when no tool results exist"


@pytest.mark.asyncio
async def test_optional_model_used_when_tool_results_already_present():
    """When ToolMessages are already in history, the optional (non-forced) model is used."""
    forced_calls: list = []
    optional_calls: list = []

    forced_model = MagicMock()
    forced_model.ainvoke = AsyncMock(side_effect=lambda msgs: (forced_calls.append(1) or _ai_msg()))

    optional_model = MagicMock()
    optional_model.ainvoke = AsyncMock(side_effect=lambda msgs: (optional_calls.append(1) or _ai_msg()))

    structured_model = MagicMock()
    structured_model.ainvoke = AsyncMock(return_value=MagicMock())

    mock_chat = MagicMock()
    mock_chat.bind_tools.side_effect = lambda tools, **kw: (
        forced_model if kw.get("tool_choice") == "any" else optional_model
    )
    mock_chat.with_structured_output.return_value = structured_model

    mock_tool = MagicMock()
    mock_tool.name = "MockTool"

    agent = _build_agent(mock_chat, mock_tool)

    existing_tool_msg = ToolMessage(
        content="result from tool", tool_call_id="tc1", name="MockTool"
    )

    await agent.ainvoke({
        "messages": [SystemMessage("system"), HumanMessage("job"), existing_tool_msg],
        "user_id": "u1",
        "require_tool_call": True,
    })

    assert len(optional_calls) == 1, "Optional model must be called when tool results are present"
    assert len(forced_calls) == 0, "Forced model must not be called when tool results already exist"


@pytest.mark.asyncio
async def test_no_forcing_on_translation_path():
    """Translation invocation (no require_tool_call key) always uses the optional model."""
    forced_calls: list = []
    optional_calls: list = []

    forced_model = MagicMock()
    forced_model.ainvoke = AsyncMock(side_effect=lambda msgs: (forced_calls.append(1) or _ai_msg()))

    optional_model = MagicMock()
    optional_model.ainvoke = AsyncMock(side_effect=lambda msgs: (optional_calls.append(1) or _ai_msg()))

    structured_model = MagicMock()
    structured_model.ainvoke = AsyncMock(return_value=MagicMock())

    mock_chat = MagicMock()
    mock_chat.bind_tools.side_effect = lambda tools, **kw: (
        forced_model if kw.get("tool_choice") == "any" else optional_model
    )
    mock_chat.with_structured_output.return_value = structured_model

    mock_tool = MagicMock()
    mock_tool.name = "MockTool"

    agent = _build_agent(mock_chat, mock_tool)

    await agent.ainvoke({
        "messages": [SystemMessage("translate sys"), HumanMessage("content")],
        "user_id": "u1",
        # require_tool_call intentionally absent — translation path
    })

    assert len(optional_calls) == 1, "Optional model must be used on the translation path"
    assert len(forced_calls) == 0, "Forced model must never be called on the translation path"
