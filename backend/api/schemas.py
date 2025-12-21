from pydantic import BaseModel

class ResumeRequest(BaseModel):
    job_description: str
    format: str = "latex"  # or "word"
    model: str = "gemini-2.5-flash"
    include_profile_picture: bool = False
