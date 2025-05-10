from abc import ABC, abstractmethod
from typing import List, Dict, Any

from utils.file_io import load_prompt

class BaseLLM(ABC):
    """
    Abstract base class for any LLM adapter.
    """
    def __init__(self,job_prompt: str ="translation_prompt",translation_prompt: str ="translation_prompt"):
        self.JOB_PROMPT = load_prompt(job_prompt)
        self.TRANSLATE_PROMPT = load_prompt(translation_prompt)

    @abstractmethod
    def bind_tools(self) -> None:
        """Bind external tools (e.g. vector DB) to the LLM."""
        pass

    @abstractmethod
    def invoke(self, messages: List[Dict[str, Any]], tools: List[Any]) -> Any:
        """Send chat messages to the LLM and return its response."""
        pass
