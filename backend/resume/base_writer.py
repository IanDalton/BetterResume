from abc import ABC, abstractmethod
from typing import List, Dict, Any
import pandas as pd

class BaseWriter(ABC):
    """
    BaseWriter is an abstract base class that provides a foundation for creating
    custom writers to process and output data. It includes methods for writing
    responses, converting to PDF, and generating files, which must be implemented
    by subclasses.
    Attributes:
        data (pd.DataFrame): A pandas DataFrame containing job data loaded from a CSV file.
    Methods:
        write(response: dict, output: str = None, to_pdf: bool = False):
            Abstract method to write the response to a file or other output.
        to_pdf(output: str, src_path: str = None) -> str:
            Abstract method to convert the response to a PDF format.
        generate_file(response: dict, output: str = None) -> str:
            Abstract method to generate a file from the response.
    """
    
    def __init__(self, template: str = None,csv_location: str = "jobs.csv",file_ending: str = None):
        data = pd.read_csv(csv_location)
        data["start_date"] = pd.to_datetime(
            data["start_date"], format="%d/%m/%Y")
        data["end_date"] = pd.to_datetime(data["end_date"], format="%d/%m/%Y")
        self.data = data
        self.file_ending = template.split(".")[-1] if template else file_ending

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