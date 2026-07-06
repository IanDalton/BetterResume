import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from api.config import LINKEDIN_PDF_MAX_BYTES
from api.schemas import LanguageRecord, LinkedInImportEntry, LinkedInImportProfile, LinkedInImportResponse
from api.utils import _validate_user_id
from utils.db_storage import DBStorage
from utils.linkedin_import import LinkedInPdfEmptyError, parse_linkedin_pdf
from utils.logging_utils import set_user_context

logger = logging.getLogger("betterresume.api.linkedin_import")
router = APIRouter()


def _is_pdf(file: UploadFile) -> bool:
    content_type = (file.content_type or "").lower()
    if content_type == "application/pdf":
        return True
    return (file.filename or "").lower().endswith(".pdf")


@router.post("/import/linkedin/{user_id}", response_model=LinkedInImportResponse)
async def import_linkedin_pdf(user_id: str, file: UploadFile = File(...)):
    """Parse a LinkedIn "Save to PDF" export and return structured data for
    the user to review -- nothing is saved server-side by this endpoint.
    """
    _validate_user_id(user_id)
    set_user_context(user_id)

    if not _is_pdf(file):
        raise HTTPException(status_code=400, detail="Upload a PDF file exported from LinkedIn (Save to PDF).")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(content) > LINKEDIN_PDF_MAX_BYTES:
        raise HTTPException(status_code=400, detail="PDF too large (max 10 MB)")

    # Best-effort audit/re-parse copy; never fail the request over this.
    try:
        storage = DBStorage()
        storage.save_file(
            user_id=user_id,
            file_type="linkedin_pdf_raw",
            content=content,
            filename=file.filename or "linkedin_export.pdf",
            mime_type="application/pdf",
        )
    except Exception:
        logger.warning("Failed to store raw LinkedIn PDF for user=%s", user_id, exc_info=True)

    try:
        result = await parse_linkedin_pdf(content)
    except LinkedInPdfEmptyError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "No readable text found in this PDF. Make sure you exported your LinkedIn "
                "profile as a PDF (Resources > Save to PDF on your profile page), not a scanned image."
            ),
        ) from exc
    except Exception as exc:
        logger.exception("LinkedIn PDF parsing failed for user=%s", user_id)
        raise HTTPException(
            status_code=502,
            detail="Could not parse this file right now. You can still add your experience manually.",
        ) from exc

    return LinkedInImportResponse(
        profile=LinkedInImportProfile(**result.profile.model_dump()),
        experience=[LinkedInImportEntry(**e.model_dump()) for e in result.experience],
        education=[LinkedInImportEntry(**e.model_dump()) for e in result.education],
        skills=result.skills,
        languages=[LanguageRecord(**l.model_dump()) for l in result.languages],
        warnings=result.warnings,
    )
