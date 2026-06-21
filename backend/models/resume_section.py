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
        _FUTURE = datetime.strptime("12/9999", "%m/%Y")  # sentinel so ongoing roles sort first

        def get_date(exp):
            # Numeric dates are MM/YYYY (language-agnostic). Any non-numeric token
            # (empty, or a localized ongoing marker like "Present"/"Presente") is
            # treated as most recent so the agent can write dates in its own language.
            if not exp.end_date:
                return _FUTURE
            try:
                return datetime.strptime(exp.end_date.strip(), "%m/%Y")
            except ValueError:
                return _FUTURE
        return sorted(v, key=get_date, reverse=True)