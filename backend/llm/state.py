from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from typing import Annotated
from models.resume import ResumeOutputFormat
class State(TypedDict): 
    messages: Annotated[list, add_messages]
    user_id: str
    structured_response: ResumeOutputFormat