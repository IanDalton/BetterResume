from pydantic import BaseModel
from typing import Annotated


class Language(BaseModel):
    name: Annotated[str, "Name of the spoken language, e.g., 'English'"]
    proficiency: Annotated[str, "Proficiency level, e.g., 'Native', 'Full professional proficiency (C2)', 'Intermediate (B2)'"]
