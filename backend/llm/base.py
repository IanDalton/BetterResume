from abc import ABC, abstractmethod
from typing import List, Dict, Any
from langchain.chat_models import init_chat_model
from utils.file_io import load_prompt
from pydantic import BaseModel
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

    def __init__(self,tools: list,model=str, output_format: BaseModel = None) -> None:

        self.tools = tools
        self.model = init_chat_model(model_name=model,tools=tools,)
        if output_format:
            self.assign_output_format(output_format)
        

    def copy(self,tools: list) -> 'BaseLLM':
        """Create a copy of the current LLM instance."""
        
        return self.__class__(tools=tools, model=self.model)

    def assign_output_format(self,output_format:BaseModel) -> None:
        self.model = self.model.with_structured_output(output_format)


    @abstractmethod
    def invoke(self, messages: List[Dict[str, Any]], tools: List[Any]) -> Any:
        """Send chat messages to the LLM and return its response."""
        pass
