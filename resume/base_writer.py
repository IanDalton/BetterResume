from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseWriter(ABC):
    """
    Abstract base class for any writer.
    """

    @abstractmethod
    def write(self,response:dict, output: str = None,to_pdf:bool=False):
        """Write the response to a file or other output."""
        pass

    @abstractmethod
    def to_pdf(self, output: str, src_path: str= None) -> str:
        """Convert the response to a PDF format."""
        pass
    
    @abstractmethod
    def generate_file(self, response: dict, output: str = None) -> str:
        """Generate a file from the response."""
        pass