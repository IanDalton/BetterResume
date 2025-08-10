import json
from langchain_core.messages import BaseMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from .base import BaseLLM
from utils.file_io import load_prompt
import os

class GeminiTool(BaseLLM):
    """
    A class that wraps around the ChatGemini client to provide additional functionality
    such as binding tools and invoking the model with messages.
    Attributes:
        client (ChatGemini): The ChatGemini client instance used for communication with the LLM.
        tools (list): A list of tools to be bound to the ChatGemini client.
    Methods:
        __init__(base_url: str, api_key: str, model: str, tools: list = None):
            Initializes the GeminiTool instance with the specified base URL, API key, model, and optional tools.
        bind_tools():
            Binds the specified tools to the ChatGemini client. Reassigns the client instance
            to ensure the tools are properly bound.
        invoke(messages: list[BaseMessage]) -> BaseMessage:
            Sends a list of messages to the ChatGemini client and returns the response.
    """
    def __init__(self, model: str, api_key: str = None, tools: list = None):
        super().__init__(tools=tools,model=model)
        api_key =  os.environ.get("GOOGLE_API_KEY", api_key)
        if not api_key:
            raise ValueError("API key must be provided or set in environment variable GOOGLE_API_KEY")
        os.environ["GOOGLE_API_KEY"] = api_key
        
        self.client = ChatGoogleGenerativeAI(
            model=model
        )
     

    def bind_tools(self):
        # your ChatGemini.bind_tools returns a new instance,
        # so reassign to self.client
        # force bind_tools to use any tool
        self.client = self.client.bind_tools(self.tools, tool_choice="required") 

    def invoke(self, messages: list[BaseMessage]) -> BaseMessage:
        # directly call the LLM
        return self.client.invoke(messages)
