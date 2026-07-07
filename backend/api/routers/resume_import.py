import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from api.config import IMPORT_PDF_MAX_BYTES
from api.schemas import LanguageRecord, ResumeImportEntry, ResumeImportProfile, ResumeImportResponse
from api.utils import _validate_user_id
from utils.db_storage import DBStorage
from utils.resume_import import ResumePdfEmptyError, parse_resume_pdf
from utils.logging_utils import set_user_context

logger = logging.getLogger("betterresume.api.resume_import")
router = APIRouter()


def _is_pdf(file: UploadFile) -> bool:
    content_type = (file.content_type or "").lower()
    if content_type == "application/pdf":
        return True
    return (file.filename or "").lower().endswith(".pdf")


@router.post("/import/resume/{user_id}", response_model=ResumeImportResponse)
async def import_resume_pdf(user_id: str, file: UploadFile = File(...)):
    """Parse an uploaded resume PDF (any resume/CV, including a LinkedIn
    "Save to PDF" export) and return structured data for the user to review --
    nothing is saved server-side by this endpoint.
    """
    _validate_user_id(user_id)
    set_user_context(user_id)

    if not _is_pdf(file):
        raise HTTPException(status_code=400, detail="Upload your resume as a PDF file.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(content) > IMPORT_PDF_MAX_BYTES:
        raise HTTPException(status_code=400, detail="PDF too large (max 10 MB)")

    # Best-effort audit/re-parse copy; never fail the request over this.
    try:
        storage = DBStorage()
        storage.save_file(
            user_id=user_id,
            file_type="resume_import_pdf_raw",
            content=content,
            filename=file.filename or "resume_import.pdf",
            mime_type="application/pdf",
        )
    except Exception:
        logger.warning("Failed to store raw resume PDF for user=%s", user_id, exc_info=True)

    try:
        result = await parse_resume_pdf(content)
    except ResumePdfEmptyError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "No readable text found in this PDF. Scanned/photographed resumes can't be "
                "parsed -- upload a text-based PDF (e.g. exported from your editor, or "
                "LinkedIn's Resources > Save to PDF)."
            ),
        ) from exc
    except Exception as exc:
        logger.exception("Resume PDF parsing failed for user=%s", user_id)
        raise HTTPException(
            status_code=502,
            detail="Could not parse this file right now. You can still add your experience manually.",
        ) from exc

    return ResumeImportResponse(
        profile=ResumeImportProfile(**result.profile.model_dump()),
        experience=[ResumeImportEntry(**e.model_dump()) for e in result.experience],
        education=[ResumeImportEntry(**e.model_dump()) for e in result.education],
        skills=result.skills,
        languages=[LanguageRecord(**l.model_dump()) for l in result.languages],
        warnings=result.warnings,
    )
