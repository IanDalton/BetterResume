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
    

    def __init__(self, tools: list) -> None:
        self.tools_by_name = {tool.name: tool for tool in tools}

    def __call__(self, inputs: dict):
        if messages := inputs.get("messages", []):
            message = messages[-1]
        else:
            raise ValueError("No message found in input")
        outputs = []
        for tool_call in message.tool_calls:
            tool_result = self.tools_by_name[tool_call["name"]].invoke(
                tool_call["args"]
            )
            outputs.append(
                ToolMessage(
                    content=json.dumps(tool_result),
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                )
            )
        return {"messages": outputs}