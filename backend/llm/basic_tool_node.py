from langchain_core.messages import ToolMessage
import json

class BasicToolNode:
    """
    A class representing a basic tool node that manages a collection of tools 
    and processes tool calls based on input messages.
    Attributes:
        tools_by_name (dict): A dictionary mapping tool names to their respective tool objects.
    Methods:
        __init__(tools: list):
            Initializes the BasicToolNode with a list of tools.
        __call__(inputs: dict) -> dict:
            Processes input messages, invokes the appropriate tools based on tool calls,
            and returns the results as a dictionary of messages.
    """
    

    def __init__(self, tools: list, require_tool: bool = True) -> None:
        self.tools_by_name = {tool.name: tool for tool in tools}
        self.require_tool = require_tool

    def __call__(self, inputs: dict):
        if messages := inputs.get("messages", []):
            message = messages[-1]
        else:
            raise ValueError("No message found in input")
        outputs = []
        # Normal path: model specified tool calls
        if getattr(message, "tool_calls", None):
            for tool_call in message.tool_calls:
                tool = self.tools_by_name.get(tool_call["name"])
                if not tool:
                    continue
                tool_result = tool.invoke(tool_call["args"])
                outputs.append(
                    ToolMessage(
                        content=json.dumps(tool_result),
                        name=tool_call["name"],
                        tool_call_id=tool_call["id"],
                    )
                )
        # Fallback: force one retrieval call with last user/AI content if none requested
        elif self.require_tool and self.tools_by_name:
            # Pick first tool deterministically
            fallback_tool_name = next(iter(self.tools_by_name))
            tool = self.tools_by_name[fallback_tool_name]
            query_text = getattr(message, "content", "") or str(message)
            try:
                tool_result = tool.invoke({"query": query_text})
            except Exception:
                # Try plain string if tool expects it
                try:
                    tool_result = tool.invoke(query_text)  # type: ignore
                except Exception as e:
                    tool_result = f"Forced tool call failed: {e}" 
            outputs.append(
                ToolMessage(
                    content=json.dumps(tool_result),
                    name=fallback_tool_name,
                    tool_call_id="forced-0",
                )
            )
        return {"messages": outputs}