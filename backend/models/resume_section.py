from pydantic import BaseModel, Field, field_validator
from typing import  Annotated

from .education import Education
from .skill import Skill
from .job_experience import JobExperience
from .language import Language
from datetime import datetime


class ResumeSection(BaseModel):
    title: Annotated[str, "Target Job Title from job description"]
    professional_summary: Annotated[str, "Brief summary (3–4 lines) highlighting relevant skills, achievements, and domain expertise."]
    experience: Annotated[list[JobExperience], Field(description="List of job experiences.", min_length=1)]
    skills: Annotated[list[Skill], Field(description="List of skills.", min_length=1)]
    education: Annotated[list[Education], "List of educational qualifications."]
    languages: Annotated[list[Language], Field(default_factory=list, description="Spoken languages with explicit proficiency levels. Only include languages provided in the user context; never invent.")]
    
    @field_validator("experience")
    def sort_experience(cls, v):
        # Sort experiences by end date (most recent first), then start date
        def get_date(exp):
            # date format is MM/YYYY, some entries might have "Present" as end_date, treat it as most recent
            if exp.end_date == "Present" or not exp.end_date:
                return datetime.strptime("12/9999", "%m/%Y")  # A date far in the future to ensure "Present" comes first
            return datetime.strptime(exp.end_date, "%m/%Y")
        return sorted(v, key=get_date, reverse=True)