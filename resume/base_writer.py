from abc import ABC, abstractmethod
from typing import List, Dict, Any
import pandas as pd

class BaseWriter(ABC):
    """
    Abstract base class for any writer.
    """
    def __init__(self, template: str = None,csv_location: str = "jobs.csv"):
        data = pd.read_csv(csv_location)
        data["start_date"] = pd.to_datetime(
            data["start_date"], format="%d/%m/%Y")
        data["end_date"] = pd.to_datetime(data["end_date"], format="%d/%m/%Y")
        self.data = data

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