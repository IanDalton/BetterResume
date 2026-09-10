from typing import Any, Dict, List, Optional
from pydantic import BaseModel

class ResumeRequest(BaseModel):
    job_description: str
    format: str = "latex"  # or "word"
    include_profile_picture: bool = False
    # Change requests from a review of a previous draft (see `llm/reviewer.py`),
    # one plain-text instruction each. They go into the generation prompt and
    # into the result cache key, so "apply improvements" always regenerates.
    improvements: List[str] = []


class ResumeAnalysisRequest(BaseModel):
    """Body of `POST /analyze-resume/{user_id}`: the job description the resume
    was generated for, the generated resume itself (the `result` payload the
    generation endpoints return, i.e. a `ResumeOutputFormat`), and the
    language the recommendations should be written in (UI language code;
    defaults to the resume's language)."""
    job_description: str
    resume: Dict[str, Any]
    language: Optional[str] = None


# Work-like entry types accepted by /upload-jobs. Personal info and languages
# have their own dedicated schemas/endpoints below (see ProfileLink,
# UserProfilePayload, LanguageRecord) -- they used to be smuggled through
# this same list via 'info'/'language' type values, which is no longer
# accepted going forward (jobs.py still tolerates it transitionally).
WORK_ENTRY_TYPES = {"job", "contract", "part-time", "project", "non-profit", "education", "certification"}


class JobRecord(BaseModel):
    """Single work/education entry record used for ingestion.

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


class ProfileLink(BaseModel):
    kind: str = "other"
    label: Optional[str] = None
    url: str


class UserProfilePayload(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    links: List[ProfileLink] = []


class LanguageRecord(BaseModel):
    name: str
    proficiency: Optional[str] = None


class LanguagesPayload(BaseModel):
    languages: List[LanguageRecord] = []
