import json
from langchain_core.messages import BaseMessage
from langchain_openai.chat_models.base import ChatOpenAI
from .base import BaseLLM

class OpenAITool(BaseLLM):
    def __init__(self, base_url: str, api_key: str, model: str, tools: list = None):
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
        self.client = self.client.bind_tools(self.tools, tool_choice="any") 

    def invoke(self, messages: list[BaseMessage]) -> BaseMessage:
        # directly call the LLM
        return self.client.invoke(messages)
