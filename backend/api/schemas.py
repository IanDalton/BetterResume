from typing import List, Optional
from pydantic import BaseModel

class ResumeRequest(BaseModel):
    job_description: str
    format: str = "latex"  # or "word"
    include_profile_picture: bool = False


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


class LinkedInImportProfile(BaseModel):
    full_name: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    links: List[ProfileLink] = []


class LinkedInImportEntry(BaseModel):
    type: str
    company: str
    description: str
    role: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class LinkedInImportResponse(BaseModel):
    """Parsed-but-unsaved LinkedIn import result, returned for user review."""
    profile: LinkedInImportProfile
    experience: List[LinkedInImportEntry] = []
    education: List[LinkedInImportEntry] = []
    skills: List[str] = []
    languages: List[LanguageRecord] = []
    warnings: List[str] = []
