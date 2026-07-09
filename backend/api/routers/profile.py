import os
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from api.config import PROFILE_PICS_BASE, PROFILE_EXTENSIONS
from api.schemas import UserProfilePayload
from api.utils import (
    _validate_user_id,
    _detect_profile_extension,
    _resolve_profile_picture_path,
    get_profile_with_links,
)
from utils.db_storage import DBStorage
from utils.logging_utils import set_user_context

logger = logging.getLogger("betterresume.api.profile")
router = APIRouter()


@router.get("/profile/{user_id}", response_model=UserProfilePayload)
async def get_profile(user_id: str):
    _validate_user_id(user_id)
    set_user_context(user_id)
    return UserProfilePayload(**get_profile_with_links(user_id))


@router.put("/profile/{user_id}", response_model=UserProfilePayload)
async def put_profile(user_id: str, payload: UserProfilePayload):
    _validate_user_id(user_id)
    set_user_context(user_id)
    storage = DBStorage()
    storage.upsert_user_profile(user_id, payload.full_name, payload.email, payload.phone, payload.address)
    storage.replace_profile_links(user_id, [link.dict() for link in payload.links])
    logger.info("Updated profile for user=%s (%d links)", user_id, len(payload.links))
    return payload

@router.post("/upload-profile-picture/{user_id}")
async def upload_profile_picture(user_id: str, file: UploadFile = File(...)):
    _validate_user_id(user_id)
    set_user_context(user_id)
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 5 MB)")
    ext = _detect_profile_extension(file)
    if not ext:
        raise HTTPException(status_code=400, detail="Unsupported image type. Upload a PNG or JPG file.")
    filename = f"profile_{user_id}{ext}"
    target_path = os.path.join(PROFILE_PICS_BASE, filename)
    # Remove any previous profile image for this user
    for existing_ext in PROFILE_EXTENSIONS:
        existing = os.path.join(PROFILE_PICS_BASE, f"profile_{user_id}{existing_ext}")
        if existing != target_path and os.path.exists(existing):
            try:
                os.remove(existing)
            except Exception:
                pass
    try:
        with open(target_path, "wb") as out:
            out.write(contents)
    except Exception as exc:
        logger.exception("Failed storing profile image for user=%s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Failed to store profile image") from exc
    logger.info("Stored profile image user=%s path=%s size=%d", user_id, target_path, len(contents))
    return {"status": "ok", "filename": filename}

@router.get("/profile-picture/{user_id}")
async def get_profile_picture(user_id: str):
    _validate_user_id(user_id)
    set_user_context(user_id)
    path = _resolve_profile_picture_path(user_id)
    if not path:
        raise HTTPException(status_code=404, detail="Profile picture not found")
    return FileResponse(path)
