import re
from datetime import datetime

from pydantic import BaseModel, field_validator
from typing import Annotated

# Values made up only of digits and common date separators are treated as an
# attempt at a numeric date and validated strictly. Anything else (empty, or
# localized free text like "Present"/"Presente"/"Octubre 2024") is allowed
# through, since the agent writes dates in the resume's own language.
_NUMERIC_DATE = re.compile(r"^[\d\s/.\-]+$")

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
        # Only enforce MM/YYYY when the value looks like a numeric date attempt.
        if _NUMERIC_DATE.match(v):
            try:
                datetime.strptime(v.strip(), "%m/%Y")
            except ValueError:
                raise ValueError("Numeric dates must be in MM/YYYY format")
        raise ValueError("Dates must be in MM/YYYY format or a localized term like 'Present'")
        
    
    