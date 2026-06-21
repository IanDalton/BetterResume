import os
import time
import logging
import hmac
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse

from api.config import OUTPUTS_BASE
from api.schemas import ResumeRequest
from api.utils import (
    _validate_user_id,
    _resolve_user_jobs_csv,
    _resolve_profile_picture_path,
    _file_sha256,
    _hash_text,
    _build_result_signature,
    _build_request_signature,
    _load_resume_cache,
    _build_signed_files,
    clean_output_dir,
    _save_resume_cache,
    get_user_store,
    sse_event,
    _hmac_sign
)
from utils.logging_utils import set_user_context
from utils.db_storage import DBStorage

from bot import Bot
from models.resume import ResumeOutputFormat
from resume import LatexResumeWriter, WordResumeWriter

logger = logging.getLogger("betterresume.api.resume")
router = APIRouter()

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "*",
}


def _record_generation(user_id, model, fmt, language, started_at, status, error=None):
    """Persist a generation event for admin statistics; never raises."""
    try:
        DBStorage().record_generation_event(
            user_id=user_id,
            model=str(model or ""),
            format=fmt,
            language=language,
            duration_ms=int((time.time() - started_at) * 1000),
            status=status,
            error=error,
        )
    except Exception:
        logger.warning("Failed to record generation event for user_id=%s", user_id, exc_info=True)


def _make_writer(fmt: str, csv_path: str, profile_path):
    writer_cls = LatexResumeWriter if fmt == "latex" else WordResumeWriter
    return writer_cls(csv_location=csv_path, profile_image_path=profile_path)


def _count_csv_rows(csv_path: str):
    try:
        import pandas as pd
        return len(pd.read_csv(csv_path))
    except Exception:
        return None


def _as_resume(result) -> ResumeOutputFormat:
    return result if isinstance(result, ResumeOutputFormat) else ResumeOutputFormat.model_validate(result)


def _serialize_result(result):
    return result.model_dump() if hasattr(result, "model_dump") else result


def _cache_payload(req: ResumeRequest, fmt, result, signature, result_signature, csv_hash, profile_hash, job_hash):
    return {
        "render_signature": signature,
        "result_signature": result_signature,
        "result": _serialize_result(result),
        "format": fmt,
        "model": req.model,
        "include_profile_picture": bool(req.include_profile_picture),
        "csv_hash": csv_hash,
        "profile_hash": profile_hash,
        "job_description_hash": job_hash,
        "generated_at": int(time.time()),
    }


def _record_resume_request(user_id: str, job_description: str):
    try:
        DBStorage().insert_resume_request(user_id, job_description)
    except Exception:
        logger.warning("Failed to record resume request for user_id=%s", user_id, exc_info=True)


@router.post("/generate-resume/{user_id}")
async def generate_resume(user_id: str, req: ResumeRequest):
    _validate_user_id(user_id)
    set_user_context(user_id)
    logger.info("Generate resume requested; format=%s model=%s", req.format, req.model)
    csv_path = _resolve_user_jobs_csv(user_id)
    logger.info("Resolved jobs CSV for user_id=%s at %s", user_id, csv_path)
    row_count = _count_csv_rows(csv_path)
    if not row_count:
        raise HTTPException(status_code=400, detail="No jobs found. Please upload your entries before generating.")
    profile_path = _resolve_profile_picture_path(user_id) if req.include_profile_picture else None
    if req.include_profile_picture and not profile_path:
        logger.info("Profile picture requested but none stored for user=%s", user_id)
    csv_hash = _file_sha256(csv_path)
    job_hash = _hash_text(req.job_description)
    _record_resume_request(user_id, req.job_description)
    profile_hash = _file_sha256(profile_path) if profile_path else None
    fmt = req.format.lower()
    result_signature = _build_result_signature(req, csv_hash, job_hash)
    signature = _build_request_signature(req, csv_hash, profile_hash, job_hash)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    cached = _load_resume_cache(out_dir) or {"results": {}, "renders": {}}
    render_entry = cached.get("renders", {}).get(signature)
    result_entry = cached.get("results", {}).get(result_signature)
    cached_result = result_entry.get("result") if result_entry else None
    files_from_cache = _build_signed_files(user_id, fmt, out_dir) if render_entry else {}

    if render_entry and cached_result is not None and files_from_cache.get("source"):
        logger.info("Reusing cached resume output for user_id=%s format=%s", user_id, fmt)
        return JSONResponse(content={"result": cached_result, "files": files_from_cache, "rows": row_count})

    if cached_result is not None:
        logger.info("Reusing cached resume content for new render user_id=%s format=%s include_image=%s", user_id, fmt, req.include_profile_picture)
        writer = _make_writer(fmt, csv_path, profile_path)
        clean_output_dir(out_dir)
        output_name = os.path.join(out_dir, f"resume{writer.file_ending}")
        try:
            typed_result = _as_resume(cached_result)
            writer.write(typed_result, output=output_name, to_pdf=True)
        except Exception as exc:
            logger.exception("Failed rewriting resume from cache: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to render cached resume")
        signed_files = _build_signed_files(user_id, fmt, out_dir)
        if signed_files.get("source"):
            _save_resume_cache(out_dir, _cache_payload(
                req, fmt, typed_result, signature, result_signature, csv_hash, profile_hash, job_hash,
            ))
        return JSONResponse(content={"result": cached_result, "files": signed_files, "rows": row_count})

    writer = _make_writer(fmt, csv_path, profile_path)
    store = get_user_store(user_id)
    clean_output_dir(out_dir)
    logger.info("Starting Bot generation; out_dir=%s", out_dir)
    bot = Bot(user_id=user_id, vector_store=store, jobs_csv=csv_path)
    gen_start = time.time()
    try:
        result = await bot.generate_resume(req.job_description)
    except Exception as exc:
        _record_generation(user_id, bot.model, fmt, None, gen_start, "error", str(exc))
        raise
    _record_generation(user_id, bot.model, fmt, result.language, gen_start, "success")
    logger.info(
        "Bot generation complete; language=%s skills=%d exp=%d",
        result.language,
        len(result.resume_section.skills),
        len(result.resume_section.experience),
    )
    # Write files in API layer for consistency
    output_name = os.path.join(out_dir, f"resume{writer.file_ending}")
    try:
        writer.write(result, output=output_name, to_pdf=True)
    except Exception as exc:
        logger.exception("Failed writing resume files: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to render resume")
    signed_files = _build_signed_files(user_id, fmt, out_dir)
    if signed_files.get("source"):
        _save_resume_cache(out_dir, _cache_payload(
            req, fmt, result, signature, result_signature, csv_hash, profile_hash, job_hash,
        ))
    else:
        logger.warning("Resume generation completed but no source file found to cache for user_id=%s", user_id)
    return JSONResponse(content={"result": _serialize_result(result), "files": signed_files, "rows": row_count})


@router.post("/generate-resume-stream/{user_id}")
async def generate_resume_stream(user_id: str, req: ResumeRequest):
    """Stream progress events for resume generation via Server-Sent Events (SSE)."""
    _validate_user_id(user_id)
    set_user_context(user_id)
    csv_path = _resolve_user_jobs_csv(user_id)
    profile_path = _resolve_profile_picture_path(user_id) if req.include_profile_picture else None
    if req.include_profile_picture and not profile_path:
        logger.info("Profile picture requested but none stored for user=%s", user_id)
    csv_hash = _file_sha256(csv_path)
    job_hash = _hash_text(req.job_description)
    _record_resume_request(user_id, req.job_description)
    profile_hash = _file_sha256(profile_path) if profile_path else None
    fmt = req.format.lower()
    result_signature = _build_result_signature(req, csv_hash, job_hash)
    signature = _build_request_signature(req, csv_hash, profile_hash, job_hash)
    store = get_user_store(user_id)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    cached = _load_resume_cache(out_dir) or {"results": {}, "renders": {}}
    render_entry = cached.get("renders", {}).get(signature)
    result_entry = cached.get("results", {}).get(result_signature)
    cached_files = _build_signed_files(user_id, fmt, out_dir) if render_entry else {}
    cached_result = result_entry.get("result") if result_entry else None

    row_count = _count_csv_rows(csv_path)
    if not row_count:
        return StreamingResponse(
            iter([sse_event({"stage": "error", "message": "No jobs found. Please upload your entries before generating."})]),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    collection = None
    col_docs = None
    try:
        collection = store.table_name
        col_docs = await store.acount_user_documents(user_id)
    except Exception:
        pass

    csv_info = {"stage": "csv_info", "rows": row_count, "collection": collection, "docs": col_docs}

    if render_entry and cached_result is not None and cached_files.get("source"):
        logger.info("Reusing cached streaming resume for user_id=%s format=%s", user_id, fmt)

        def cached_event_generator():
            try:
                yield sse_event(csv_info)
                yield sse_event({"stage": "cached", "message": "Using cached resume output"})
                yield sse_event({
                    "stage": "done",
                    "message": "Resume generation complete",
                    "result": cached_result,
                    "files": cached_files,
                })
            except Exception as exc:
                logger.exception("Failed while streaming cached resume: %s", exc)
                yield sse_event({"stage": "error", "message": str(exc)})

        return StreamingResponse(cached_event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)

    if cached_result is not None:
        logger.info(
            "Re-rendering cached resume content for stream user_id=%s format=%s include_image=%s",
            user_id, fmt, req.include_profile_picture,
        )

        def cached_rerender_generator():
            try:
                yield sse_event(csv_info)
                yield sse_event({"stage": "cached", "message": "Reusing cached resume content"})
                clean_output_dir(out_dir)
                writer = _make_writer(fmt, csv_path, profile_path)
                output_name = os.path.join(out_dir, f"resume{writer.file_ending}")
                try:
                    typed_result = _as_resume(cached_result)
                    writer.write(typed_result, output=output_name, to_pdf=True)
                except Exception as exc:
                    raise RuntimeError(f"Failed to render cached resume: {exc}")
                files = _build_signed_files(user_id, fmt, out_dir)
                if files.get("source"):
                    _save_resume_cache(out_dir, _cache_payload(
                        req, fmt, typed_result, signature, result_signature, csv_hash, profile_hash, job_hash,
                    ))
                yield sse_event({
                    "stage": "done",
                    "message": "Resume generation complete",
                    "result": cached_result,
                    "files": files,
                })
            except Exception as exc:
                logger.exception("Failed while streaming cached resume rerender: %s", exc)
                yield sse_event({"stage": "error", "message": str(exc)})

        return StreamingResponse(cached_rerender_generator(), media_type="text/event-stream", headers=SSE_HEADERS)

    writer = _make_writer(fmt, csv_path, profile_path)
    clean_output_dir(out_dir)
    logger.info("Starting streaming generation; format=%s model=%s out_dir=%s", req.format, req.model, out_dir)
    bot = Bot(user_id=user_id, vector_store=store, jobs_csv=csv_path)

    async def event_generator():
        gen_start = time.time()
        try:
            yield sse_event(csv_info)
            async for event in bot.generate_resume_progress(req.job_description):
                if event.get("stage") == "done":
                    # Write files here, based on final result
                    output_name = os.path.join(out_dir, f"resume{writer.file_ending}")
                    try:
                        result_obj = event.get("result")
                        _record_generation(
                            user_id, bot.model, fmt,
                            getattr(result_obj, "language", None), gen_start, "success",
                        )
                        writer.write(result_obj, output=output_name, to_pdf=True)
                        files = _build_signed_files(user_id, fmt, out_dir)
                        event["files"] = files
                        event["result"] = _serialize_result(result_obj)
                        if files.get("source"):
                            _save_resume_cache(out_dir, _cache_payload(
                                req, fmt, result_obj, signature, result_signature, csv_hash, profile_hash, job_hash,
                            ))
                        else:
                            logger.warning("Streaming generation done but source missing for caching user_id=%s", user_id)
                    except Exception as exc:
                        logger.exception("Streaming: file write failed: %s", exc)
                        event = {"stage": "error", "message": f"Failed writing resume: {exc}"}
                yield sse_event(event)
        except Exception as e:
            logger.exception("Streaming generation failed")
            _record_generation(user_id, bot.model, fmt, None, gen_start, "error", str(e))
            yield sse_event({"stage": "error", "message": str(e)})

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/download/{user_id}/{filename}")
async def download_file(user_id: str, filename: str, request: Request):
    _validate_user_id(user_id)
    set_user_context(user_id)
    # Security: basic path traversal guard
    if ".." in filename or filename.startswith('/'):
        raise HTTPException(status_code=400, detail="Invalid filename")
    # Require signed URL parameters
    try:
        exp_q = request.query_params.get("exp")
        sig_q = request.query_params.get("sig")
        if not exp_q or not sig_q:
            raise HTTPException(status_code=403, detail="Missing signature")
        exp = int(exp_q)
        if exp < int(time.time()):
            raise HTTPException(status_code=410, detail="Link expired")
        expected = _hmac_sign(user_id, filename, exp)
        # Constant-time comparison
        if not hmac.compare_digest(expected, sig_q):
            raise HTTPException(status_code=403, detail="Invalid signature")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid signature")
    path = os.path.join(OUTPUTS_BASE, user_id, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    logger.info("Downloading file %s", filename)
    return FileResponse(path)
