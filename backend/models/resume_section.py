from pydantic import BaseModel, Field
from typing import  Annotated

from .education import Education
from .skill import Skill
from .job_experience import JobExperience


class ResumeSection(BaseModel):
    title: Annotated[str, "Target Job Title from job description"]
    professional_summary: Annotated[str, "Brief summary (3–4 lines) highlighting relevant skills, achievements, and domain expertise."]
    experience: Annotated[list[JobExperience], Field(description="List of job experiences.", min_length=1)]
    skills: Annotated[list[Skill], Field(description="List of skills.", min_length=1)]
    education: Annotated[list[Education], "List of educational qualifications."]