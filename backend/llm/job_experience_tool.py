from typing import Optional, Type, Any
from langchain.tools import BaseTool
from pydantic import Field
from utils.db_storage import DBStorage
import logging

class GetLatestJobExperienceTool(BaseTool):
    name: str = "get_latest_job_experience"
    description: str = "Get the latest job experience for the user to avoid gaps in the resume."
    user_id: Optional[str] = Field(default=None)
    _user_id: Optional[str] = None # This will be set by BasicToolNode

    def _run(self):
        # Sync implementation
        return self._get_latest_experience()

    async def _arun(self):
        # Async implementation
        return self._get_latest_experience()

    def _get_latest_experience(self):
        uid = self._user_id or self.user_id
        if not uid:
            return "User ID not provided."
        
        storage = DBStorage()
        experiences = storage.get_job_experiences(uid)
        
        if not experiences:
            return "No job experiences found."
            
        # Sort by end_date or start_date to find the latest
        def get_date(exp):
            # Try to parse date or just use string comparison if format is consistent (YYYY-MM-DD)
            # Assuming ISO format or similar sortable string
            return exp.get('end_date') or exp.get('start_date') or ""
            
        sorted_experiences = sorted(experiences, key=get_date, reverse=True)
        if sorted_experiences:
            return sorted_experiences[0]
        return "No job experiences found."
