from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Type, Union
from langchain.agents import create_agent
from utils.file_io import load_prompt
from pydantic import BaseModel
from langchain_core.messages import BaseMessage
from llm.state import State
from langchain.agents.structured_output import ToolStrategy
class BaseLLM(ABC):
    """BaseLLM is an abstract base class that serves as a blueprint for creating adapters for 
    Large Language Models (LLMs). It provides a structure for initializing prompts and 
    defining essential methods that must be implemented by subclasses.
    Attributes:
        JOB_PROMPT (str): The job-specific prompt loaded from a file or resource.
        TRANSLATE_PROMPT (str): The translation-specific prompt loaded from a file or resource.
    Methods:
        bind_tools():
            Abstract method to bind external tools (e.g., vector databases) to the LLM. 
            This method must be implemented by subclasses.
        invoke(messages: List[Dict[str, Any]], tools: List[Any]) -> Any:
            Abstract method to send chat messages to the LLM and return its response. 
            This method must be implemented by subclasses.
    """

    def __init__(
        self,
        tools: list,
        model: str,
        output_format: Optional[Union[Type[BaseModel], BaseModel]] = None,
    ) -> None:

        self.JOB_PROMPT = load_prompt("job_prompt")
        self.TRANSLATE_PROMPT = load_prompt("translation_prompt")
        self.tools = tools
        # Keep a reference to the desired structured output format (Pydantic model or class)
        self.output_format: Optional[Union[Type[BaseModel], BaseModel]] = output_format

        self.model = create_agent(
            model=model,
            tools=tools,
            response_format=ToolStrategy(output_format),
            state_schema=State,
        )

        
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