from pydantic import BaseModel
from typing import Annotated

class JobExperience(BaseModel):
    position: Annotated[str, "Job position title"]
    company: Annotated[str, "Company Name or Descriptor (e.g., 'Global Consulting Firm')"]
    location: Annotated[str, "City, State/Country"]
    start_date: Annotated[str, "Start date in MM/YYYY format"]
    end_date: Annotated[str, "End date in MM/YYYY format or 'Present'"]
    description: Annotated[str, "3–4 bullets, each starting with an action verb and including tools, outcomes, and metrics."]