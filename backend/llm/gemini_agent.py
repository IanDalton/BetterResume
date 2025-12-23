import json
import os
import logging
import time
import threading
import random
from typing import Callable, Any, Optional, Union, List
from pydantic import BaseModel
from langchain_core.messages import BaseMessage
from langchain.chat_models import init_chat_model
from .base import BaseLLM
from utils.file_io import load_prompt

class GeminiAgent(BaseLLM):
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
    def __init__(self, tools, output_format:BaseModel = None, model: str = "google_genai:gemini-2.5-flash-lite"):
        tools_list = tools if isinstance(tools, list) else [tools]
        super().__init__(tools_list, model=model, output_format=output_format)
    def invoke(self, inputs: dict):
        return self.model.invoke(inputs)
    async def ainvoke(self, inputs: dict):
        return await self.model.ainvoke(inputs)