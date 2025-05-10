from typing import Dict, Any

class JobParser:
    """
    Optional: parse raw job description text into structured fields.
    """
    @staticmethod
    def extract_language_and_title(job_text: str) -> Dict[str, str]:
        # stub: detect title and language by simple heuristics or NLP
        # return e.g. {"title": "Data Scientist", "language": "EN"}
        return {"title": "", "language": "EN"}