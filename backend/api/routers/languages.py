import logging
from fastapi import APIRouter

from api.schemas import LanguagesPayload, LanguageRecord
from api.utils import _validate_user_id
from utils.db_storage import DBStorage
from utils.logging_utils import set_user_context

logger = logging.getLogger("betterresume.api.languages")
router = APIRouter()


@router.get("/languages/{user_id}", response_model=LanguagesPayload)
async def get_languages(user_id: str):
    _validate_user_id(user_id)
    set_user_context(user_id)
    storage = DBStorage()
    languages = storage.get_user_languages(user_id)
    return LanguagesPayload(languages=[LanguageRecord(**lang) for lang in languages])


@router.put("/languages/{user_id}", response_model=LanguagesPayload)
async def put_languages(user_id: str, payload: LanguagesPayload):
    _validate_user_id(user_id)
    set_user_context(user_id)
    storage = DBStorage()
    storage.replace_user_languages(user_id, [lang.dict() for lang in payload.languages])
    logger.info("Updated %d languages for user=%s", len(payload.languages), user_id)
    return payload
