from fastapi import APIRouter, HTTPException

from api.state import USER_TOOLS
from api.utils import _validate_user_id
from utils.logging_utils import set_user_context

router = APIRouter()

@router.get("/users")
async def list_users():
    return {"users": list(USER_TOOLS.keys())}

@router.delete("/users/{user_id}")
async def clear_user(user_id: str):
    _validate_user_id(user_id)
    set_user_context(user_id)
    # Drop the user's collection and remove cache entry
    if user_id not in USER_TOOLS:
        raise HTTPException(status_code=404, detail="User not found")
    tool = USER_TOOLS.pop(user_id)
    try:
        tool.delete_user_documents(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete user documents: {e}")
    return {"status": "deleted", "user_id": user_id}
