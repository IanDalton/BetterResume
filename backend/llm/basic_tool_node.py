from langchain_core.messages import ToolMessage
import json
import asyncio

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
    

    def __init__(self, tools: list, require_tool: bool = False) -> None:
        self.tools_by_name = {tool.name: tool for tool in tools}
        self.require_tool = require_tool

    async def ainvoke(self, inputs: dict):
        if messages := inputs.get("messages", []):
            message = messages[-1]
        else:
            raise ValueError("No message found in input")
        outputs = []
        # Extract user_id from state for tools that need it
        user_id = inputs.get("user_id")
        
        # Normal path: model specified tool calls
        if getattr(message, "tool_calls", None):
            for tool_call in message.tool_calls:
                tool = self.tools_by_name.get(tool_call["name"])
                if not tool:
                    continue
                
                # Inject user_id into tool if it has this attribute
                if hasattr(tool, 'user_id') and user_id:
                    tool._user_id = user_id
                
                if not hasattr(tool, "a_invoke"):
                    tool_result = await asyncio.to_thread(tool.invoke, tool_call["args"])
                else:
                    tool_result = await tool.a_invoke(tool_call["args"])
                outputs.append(
                    ToolMessage(
                        content=json.dumps(tool_result),
                        name=tool_call["name"],
                        tool_call_id=tool_call["id"],
                    )
                )
  
            return {"messages": outputs}
        else:
            # Fallback path: no tool calls found
            if self.require_tool:
                raise ValueError("No tool calls found in the message")
            return {"messages": []}