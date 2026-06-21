from datetime import datetime

from pydantic import BaseModel, field_validator
from typing import Annotated

class JobExperience(BaseModel):
    position: Annotated[str, "Job position title"]
    company: Annotated[str, "Company Name or Descriptor (e.g., 'Global Consulting Firm')"]
    location: Annotated[str, "City, State/Country"]
    start_date: Annotated[str, "Start date in MM/YYYY format"]
    end_date: Annotated[str, "End date in MM/YYYY format or 'Present'"]
    description: Annotated[str, "3–4 bullets, each starting with an action verb and including tools, outcomes, and metrics."]
    
    @field_validator("start_date", "end_date")
    def validate_date_format(cls, v):
        if v.lower() == "present":
            return "Present"
        try:
            datetime.strptime(v, "%m/%Y")
        except ValueError:
            raise ValueError("Date must be in MM/YYYY format or 'Present'")
        return v
        
    
    