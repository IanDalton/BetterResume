from pydantic import BaseModel, Field
from typing import Annotated
from .resume_section import ResumeSection


class ResumeOutputFormat(BaseModel):
    language: Annotated[str, Field(description="The language of the resume, e.g., 'ES/EN/FR/DE/IT/PT'")]
    resume_section: Annotated[ResumeSection, Field(description="The main content of the resume")] 