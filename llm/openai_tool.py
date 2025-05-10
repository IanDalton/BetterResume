import json
from langchain_core.messages import BaseMessage
from langchain_openai.chat_models.base import ChatOpenAI
from .base import BaseLLM
from utils.file_io import load_prompt

class OpenAITool(BaseLLM):
    """
    A class that wraps around the ChatOpenAI client to provide additional functionality
    such as binding tools and invoking the model with messages.
    Attributes:
        client (ChatOpenAI): The ChatOpenAI client instance used for communication with the LLM.
        tools (list): A list of tools to be bound to the ChatOpenAI client.
    Methods:
        __init__(base_url: str, api_key: str, model: str, tools: list = None):
            Initializes the OpenAITool instance with the specified base URL, API key, model, and optional tools.
        bind_tools():
            Binds the specified tools to the ChatOpenAI client. Reassigns the client instance
            to ensure the tools are properly bound.
        invoke(messages: list[BaseMessage]) -> BaseMessage:
            Sends a list of messages to the ChatOpenAI client and returns the response.
    """
    def __init__(self, base_url: str, api_key: str, model: str, tools: list = None):
        super().__init__()
        self.client = ChatOpenAI(
            base_url=base_url,
            api_key=api_key,
            model=model
        )
        self.tools = tools
        

    def bind_tools(self):
        # your ChatOpenAI .bind_tools returns a new instance,
        # so reassign to self.client
        # force bind_tools to use any tool
        self.client = self.client.bind_tools(self.tools, tool_choice="required") 

    def invoke(self, messages: list[BaseMessage]) -> BaseMessage:
        # directly call the LLM
        return self.client.invoke(messages)
