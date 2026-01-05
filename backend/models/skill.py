from pydantic import BaseModel
from typing import  Annotated

class Skill(BaseModel):
    name: Annotated[str, "Name of the skill or technology"]
    description: Annotated[str, "Impact-oriented explanation with measurable result."]