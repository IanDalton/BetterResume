from pydantic import BaseModel


from typing import Annotated


class Education(BaseModel):
    institution: Annotated[str, "Name of the educational institution"]
    degree: Annotated[str, "Degree obtained or pursued"]
    dates: Annotated[str, "Start - End dates in MM/YYYY format"]