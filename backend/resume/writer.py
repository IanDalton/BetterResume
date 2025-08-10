from typing import Dict, Any, List
import json

class ResumeWriter:
    """
    Assemble LLM output into final JSON, or format sections.
    """
    @staticmethod
    def clean_tools_output(raw: str) -> str:
        # strip markdown fences, ensure valid JSON
        return raw.replace("```json", "").replace("```", "").strip()

    @staticmethod
    def to_json(raw: str) -> Dict[str, Any]:

        cleaned = ResumeWriter.clean_tools_output(raw)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}")