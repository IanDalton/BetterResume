from pydantic import BaseModel
from typing import Annotated
from .resume_section import ResumeSection


class ResumeOutputFormat(BaseModel):
    language: Annotated[str, "The language of the resume, e.g., 'ES/EN/FR/DE/IT/PT'"]
    resume_section: Annotated[ResumeSection, "The main content of the resume"]