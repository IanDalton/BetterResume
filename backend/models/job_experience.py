from datetime import datetime

from pydantic import BaseModel, field_validator
from typing import Annotated

class JobExperience(BaseModel):
    position: Annotated[str, "Job position title"]
    company: Annotated[str, "Company Name or Descriptor (e.g., 'Global Consulting Firm')"]
    location: Annotated[str, "City, State/Country"]
    start_date: Annotated[str, "Start date in MM/YYYY format"]
    end_date: Annotated[str, "End date in MM/YYYY format or the localized 'Present'"]
    description: Annotated[str, "3–4 bullets, each starting with an action verb and including tools, outcomes, and metrics."]

    @field_validator("start_date", "end_date")
    def validate_date_format(cls, v):
        if v is None or not v.strip():
            return v
        # Real dates are always numeric MM/YYYY (language-agnostic), so any value
        # containing digits must match that format — this rejects localized
        # month-name dates like "Octubre 2024" which would not be sortable.
        if any(ch.isdigit() for ch in v):
            try:
                datetime.strptime(v.strip(), "%m/%Y")
            except ValueError:
                raise ValueError("Dates with numbers must be in MM/YYYY format")
            return v
        # No digits: a localized ongoing marker like "Present"/"Presente". Allow it.
        return v
        
    
    