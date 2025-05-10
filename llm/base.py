from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseLLM(ABC):
    """
    Abstract base class for any LLM adapter.
    """

    @abstractmethod
    def bind_tools(self) -> None:
        """Bind external tools (e.g. vector DB) to the LLM."""
        pass

    @abstractmethod
    def invoke(self, messages: List[Dict[str, Any]], tools: List[Any]) -> Any:
        """Send chat messages to the LLM and return its response."""
        pass
