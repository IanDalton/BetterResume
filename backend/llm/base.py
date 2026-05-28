from abc import ABC, abstractmethod
from typing import List, Any, Optional, Type, Union
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from utils.file_io import load_prompt
from pydantic import BaseModel
from langchain_core.messages import BaseMessage, ToolMessage
from llm.state import State


class BaseLLM(ABC):
    def __init__(
        self,
        tools: list,
        model: str,
        output_format: Optional[Union[Type[BaseModel], BaseModel]] = None,
    ) -> None:
        self.JOB_PROMPT = load_prompt("job_prompt")
        self.TRANSLATE_PROMPT = load_prompt("translation_prompt")
        self.tools = tools
        self.output_format: Optional[Union[Type[BaseModel], BaseModel]] = output_format

        provider, model_name = model.split(":", 1)
        chat_model = init_chat_model(model_name, model_provider=provider)

        model_with_tools = chat_model.bind_tools(tools) if tools else chat_model
        # "any" means the model MUST call at least one of the bound tools
        model_forced_tools = chat_model.bind_tools(tools, tool_choice="any") if tools else chat_model
        model_structured = (
            chat_model.with_structured_output(output_format) if output_format else chat_model
        )

        def _has_tool_results(messages: list) -> bool:
            return any(isinstance(m, ToolMessage) for m in messages)

        async def call_agent(state: State):
            messages = state["messages"]
            remaining = state.get("remaining_steps", 10)
            require_tool = state.get("require_tool_call", False)

            if tools and require_tool and not _has_tool_results(messages):
                # First call with tool forcing: model must retrieve context before writing
                response = await model_forced_tools.ainvoke(messages)
            else:
                response = await model_with_tools.ainvoke(messages)

            return {"messages": [response], "remaining_steps": max(0, remaining - 1)}

        def route_after_agent(state: State) -> str:
            last = state["messages"][-1]
            remaining = state.get("remaining_steps", 0)
            if tools and remaining > 0 and getattr(last, "tool_calls", None):
                return "tools"
            return "generate"

        async def generate_structured(state: State):
            if output_format:
                response = await model_structured.ainvoke(state["messages"])
                return {"structured_response": response}
            return {"structured_response": state["messages"][-1]}

        graph = StateGraph(State)
        graph.add_node("agent", call_agent)
        graph.add_node("generate", generate_structured)

        if tools:
            graph.add_node("tools", ToolNode(tools))
            graph.add_edge("tools", "agent")

        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent",
            route_after_agent,
            {"tools": "tools", "generate": "generate"} if tools else {"generate": "generate"},
        )
        graph.add_edge("generate", END)

        self.model = graph.compile()

        
    def get_tools(self) -> list:
        return self.tools
    def copy(self,tools: list) -> 'BaseLLM':
        """Create a copy of the current LLM instance."""
        
        return self.__class__(tools=tools, model=self.model)


    @abstractmethod
    def invoke(self, messages: List[BaseMessage]) -> Any:
        """Send chat messages to the LLM and return its response."""
        pass
    @abstractmethod
    async def ainvoke(self, messages: List[BaseMessage]) -> Any:
        """Asynchronously send chat messages to the LLM and return its response."""
        pass