from typing import List, Optional
from pydantic import BaseModel

class ResumeRequest(BaseModel):
    job_description: str
    format: str = "latex"  # or "word"
    model: str = "gemini-2.5-flash"
    include_profile_picture: bool = False


class JobRecord(BaseModel):
    """Single job/entry record used for ingestion.

    Minimum required fields: company, description, type.
    Optional fields: role, location, start_date, end_date.
    """
    company: str
    description: str
    type: str
    role: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class JobUploadRequest(BaseModel):
    jobs: List[JobRecord]
