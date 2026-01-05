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
    get_user_tool,
    sse_event,
    _hmac_sign
)
from utils.logging_utils import set_user_context
from utils.db_storage import DBStorage

from bot import Bot
from models.resume import ResumeOutputFormat
from resume import LatexResumeWriter, WordResumeWriter
from llm.gemini_agent import GeminiAgent
from llm.job_experience_tool import GetLatestJobExperienceTool

logger = logging.getLogger("betterresume.api.resume")
router = APIRouter()

@router.post("/generate-resume/{user_id}")
async def generate_resume(user_id: str, req: ResumeRequest):
    _validate_user_id(user_id)
    set_user_context(user_id)
    logger.info("Generate resume requested; format=%s model=%s", req.format, req.model)
    csv_path = _resolve_user_jobs_csv(user_id)
    logger.info("Resolved jobs CSV for user_id=%s at %s", user_id, csv_path)
    # Row count for response metadata
    row_count = None
    try:
        import pandas as pd
        row_count = len(pd.read_csv(csv_path))
    except Exception:
        pass
    if not row_count:
        raise HTTPException(status_code=400, detail="No jobs found. Please upload your entries before generating.")
    profile_path = _resolve_profile_picture_path(user_id) if req.include_profile_picture else None
    if req.include_profile_picture and not profile_path:
        logger.info("Profile picture requested but none stored for user=%s", user_id)
    csv_hash = _file_sha256(csv_path)
    job_hash = _hash_text(req.job_description)
    try:
        DBStorage().insert_resume_request(user_id, req.job_description)
    except Exception:
        logger.warning("Failed to record resume request for user_id=%s", user_id, exc_info=True)
    profile_hash = _file_sha256(profile_path) if profile_path else None
    fmt = req.format.lower()
    result_signature = _build_result_signature(req, csv_hash, job_hash)
    signature = _build_request_signature(req, csv_hash, profile_hash, job_hash)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    cached = _load_resume_cache(out_dir) or {"results": {}, "renders": {}}
    cached_renders = cached.get("renders", {})
    cached_results = cached.get("results", {})
    render_entry = cached_renders.get(signature)
    result_entry = cached_results.get(result_signature)
    cached_result = result_entry.get("result") if result_entry else None
    files_from_cache = _build_signed_files(user_id, fmt, out_dir) if render_entry else {}

    if render_entry and cached_result is not None and files_from_cache.get("source"):
        logger.info("Reusing cached resume output for user_id=%s format=%s", user_id, fmt)
        return JSONResponse(content={"result": cached_result, "files": files_from_cache, "rows": row_count})

    if cached_result is not None:
        logger.info("Reusing cached resume content for new render user_id=%s format=%s include_image=%s", user_id, fmt, req.include_profile_picture)
        writer = (
            LatexResumeWriter(csv_location=csv_path, profile_image_path=profile_path)
            if fmt == "latex"
            else WordResumeWriter(csv_location=csv_path, profile_image_path=profile_path)
        )
        clean_output_dir(out_dir)
        abs_base = os.path.join(out_dir, "resume")
        output_name = f"{abs_base}{writer.file_ending}"
        try:
            typed_result = (
                cached_result if isinstance(cached_result, ResumeOutputFormat)
                else ResumeOutputFormat.model_validate(cached_result)
            )
            writer.write(typed_result, output=output_name, to_pdf=True)
        except Exception as exc:
            logger.exception("Failed rewriting resume from cache: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to render cached resume")
        signed_files = _build_signed_files(user_id, fmt, out_dir)
        if signed_files.get("source"):
            cache_payload = {
                "render_signature": signature,
                "result_signature": result_signature,
                "result": (typed_result.model_dump() if isinstance(typed_result, ResumeOutputFormat) else cached_result),
                "format": fmt,
                "model": req.model,
                "include_profile_picture": bool(req.include_profile_picture),
                "csv_hash": csv_hash,
                "profile_hash": profile_hash if req.include_profile_picture else None,
                "job_description_hash": job_hash,
                "generated_at": int(time.time()),
            }
            _save_resume_cache(out_dir, cache_payload)
        return JSONResponse(content={"result": cached_result, "files": signed_files, "rows": row_count})

    writer = (
        LatexResumeWriter(csv_location=csv_path, profile_image_path=profile_path)
        if fmt == "latex"
        else WordResumeWriter(csv_location=csv_path, profile_image_path=profile_path)
    )
    tool = get_user_tool(user_id)
    latest_job_tool = GetLatestJobExperienceTool(user_id=user_id)
    clean_output_dir(out_dir)
    logger.info("Starting Bot generation; out_dir=%s", out_dir)
    bot = Bot(
        writer=writer,
        llm=GeminiAgent(tools=[tool, latest_job_tool], output_format=ResumeOutputFormat),
        tool=tool,
        user_id=user_id,
        auto_ingest=True,
        jobs_csv=csv_path,
    )
    # Important: use absolute output base to avoid races due to process cwd changes
    abs_base = os.path.join(out_dir, "resume")
    result = await bot.generate_resume(req.job_description, output_basename=abs_base)
    logger.info(
        "Bot generation complete; language=%s skills=%d exp=%d",
        result.language,
        len(result.resume_section.skills),
        len(result.resume_section.experience),
    )
    # Write files in API layer for consistency
    output_name = f"{abs_base}{writer.file_ending}"
    try:
        writer.write(result, output=output_name, to_pdf=True)
    except Exception as exc:
        logger.exception("Failed writing resume files: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to render resume")
    signed_files = _build_signed_files(user_id, fmt, out_dir)
    if signed_files.get("source"):
        cache_payload = {
            "render_signature": signature,
            "result_signature": result_signature,
            "result": (result.model_dump() if hasattr(result, "model_dump") else result),
            "format": fmt,
            "model": req.model,
            "include_profile_picture": bool(req.include_profile_picture),
            "csv_hash": csv_hash,
            "profile_hash": profile_hash,
            "job_description_hash": job_hash,
            "generated_at": int(time.time()),
        }
        _save_resume_cache(out_dir, cache_payload)
    else:
        logger.warning("Resume generation completed but no source file found to cache for user_id=%s", user_id)
    return JSONResponse(content={"result": (result.model_dump() if hasattr(result, "model_dump") else result), "files": signed_files, "rows": row_count})

@router.post("/generate-resume-stream/{user_id}")
async def generate_resume_stream(user_id: str, req: ResumeRequest):
    _validate_user_id(user_id)
    set_user_context(user_id)
    """Stream progress events for resume generation via Server-Sent Events (SSE)."""
    csv_path = _resolve_user_jobs_csv(user_id)
    profile_path = _resolve_profile_picture_path(user_id) if req.include_profile_picture else None
    if req.include_profile_picture and not profile_path:
        logger.info("Profile picture requested but none stored for user=%s", user_id)
    csv_hash = _file_sha256(csv_path)
    job_hash = _hash_text(req.job_description)
    try:
        DBStorage().insert_resume_request(user_id, req.job_description)
    except Exception:
        logger.warning("Failed to record resume request for user_id=%s (stream)", user_id, exc_info=True)
    profile_hash = _file_sha256(profile_path) if profile_path else None
    fmt = req.format.lower()
    result_signature = _build_result_signature(req, csv_hash, job_hash)
    signature = _build_request_signature(req, csv_hash, profile_hash, job_hash)
    tool = get_user_tool(user_id)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    cached = _load_resume_cache(out_dir) or {"results": {}, "renders": {}}
    cached_renders = cached.get("renders", {})
    cached_results = cached.get("results", {})
    render_entry = cached_renders.get(signature)
    result_entry = cached_results.get(result_signature)
    cached_files = _build_signed_files(user_id, fmt, out_dir) if render_entry else {}
    cached_result = result_entry.get("result") if result_entry else None
    # Pre-calc row count for early event
    row_count = None
    collection = None
    col_docs = None
    try:
        import pandas as pd
        row_count = len(pd.read_csv(csv_path))
    except Exception:
        pass
    if not row_count:
        # early SSE error with headers
        early_headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "*",
        }
        return StreamingResponse(
            iter([sse_event({"stage":"error","message":"No jobs found. Please upload your entries before generating."})]),
            media_type="text/event-stream",
            headers=early_headers,
        )
    try:
        collection = tool.collection_name
        col_docs = tool._collection.count()
    except Exception:
        pass

    sse_headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "*",
    }

    if render_entry and cached_result is not None and cached_files.get("source"):
        logger.info("Reusing cached streaming resume for user_id=%s format=%s", user_id, fmt)

        def cached_event_generator():
            try:
                yield sse_event({"stage": "csv_info", "rows": row_count, "collection": collection, "docs": col_docs})
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

        return StreamingResponse(cached_event_generator(), media_type="text/event-stream", headers=sse_headers)

    if cached_result is not None:
        logger.info(
            "Re-rendering cached resume content for stream user_id=%s format=%s include_image=%s",
            user_id,
            fmt,
            req.include_profile_picture,
        )

        def cached_rerender_generator():
            try:
                yield sse_event({"stage": "csv_info", "rows": row_count, "collection": collection, "docs": col_docs})
                yield sse_event({"stage": "cached", "message": "Reusing cached resume content"})
                clean_output_dir(out_dir)
                writer = (
                    LatexResumeWriter(csv_location=csv_path, profile_image_path=profile_path)
                    if fmt == "latex"
                    else WordResumeWriter(csv_location=csv_path, profile_image_path=profile_path)
                )
                abs_base = os.path.join(out_dir, "resume")
                output_name = f"{abs_base}{writer.file_ending}"
                try:
                    typed_result = (
                        cached_result if isinstance(cached_result, ResumeOutputFormat)
                        else ResumeOutputFormat.model_validate(cached_result)
                    )
                    writer.write(typed_result, output=output_name, to_pdf=True)
                except Exception as exc:
                    raise RuntimeError(f"Failed to render cached resume: {exc}")
                files = _build_signed_files(user_id, fmt, out_dir)
                if files.get("source"):
                    cache_payload = {
                        "render_signature": signature,
                        "result_signature": result_signature,
                        "result": (typed_result.model_dump() if isinstance(typed_result, ResumeOutputFormat) else cached_result),
                        "format": fmt,
                        "model": req.model,
                        "include_profile_picture": bool(req.include_profile_picture),
                        "csv_hash": csv_hash,
                        "profile_hash": profile_hash if req.include_profile_picture else None,
                        "job_description_hash": job_hash,
                        "generated_at": int(time.time()),
                    }
                    _save_resume_cache(out_dir, cache_payload)
                yield sse_event({
                    "stage": "done",
                    "message": "Resume generation complete",
                    "result": cached_result,
                    "files": files,
                })
            except Exception as exc:
                logger.exception("Failed while streaming cached resume rerender: %s", exc)
                yield sse_event({"stage": "error", "message": str(exc)})

        return StreamingResponse(cached_rerender_generator(), media_type="text/event-stream", headers=sse_headers)

    writer = (
        LatexResumeWriter(csv_location=csv_path, profile_image_path=profile_path)
        if fmt == "latex"
        else WordResumeWriter(csv_location=csv_path, profile_image_path=profile_path)
    )
    clean_output_dir(out_dir)
    logger.info("Starting streaming generation; format=%s model=%s out_dir=%s", req.format, req.model, out_dir)
    latest_job_tool = GetLatestJobExperienceTool(user_id=user_id)
    bot = Bot(
        writer=writer,
        llm=GeminiAgent(tools=[tool, latest_job_tool], output_format=ResumeOutputFormat),
        tool=tool,
        user_id=user_id,
        auto_ingest=True,
        jobs_csv=csv_path,
    )

    async def event_generator():
        try:
            # Send initial CSV info event
            yield sse_event({"stage": "csv_info", "rows": row_count, "collection": collection, "docs": col_docs})
            abs_base = os.path.join(out_dir, "resume")
            async for event in bot.generate_resume_progress(req.job_description):
                if event.get("stage") == "done":
                    # Write files here, based on final result
                    output_name = f"{abs_base}{writer.file_ending}"
                    try:
                        result_obj = event.get("result")
                        writer.write(result_obj, output=output_name, to_pdf=True)
                        files = _build_signed_files(user_id, fmt, out_dir)
                        event["files"] = files
                        # Serialize result for JSON encoding
                        if hasattr(result_obj, "model_dump"):
                            event["result"] = result_obj.model_dump()
                        if files.get("source"):
                            cache_payload = {
                                "render_signature": signature,
                                "result_signature": result_signature,
                                "result": (result_obj.model_dump() if hasattr(result_obj, "model_dump") else result_obj),
                                "format": fmt,
                                "model": req.model,
                                "include_profile_picture": bool(req.include_profile_picture),
                                "csv_hash": csv_hash,
                                "profile_hash": profile_hash,
                                "job_description_hash": job_hash,
                                "generated_at": int(time.time()),
                            }
                            _save_resume_cache(out_dir, cache_payload)
                        else:
                            logger.warning("Streaming generation done but source missing for caching user_id=%s", user_id)
                    except Exception as exc:
                        logger.exception("Streaming: file write failed: %s", exc)
                        event = {"stage": "error", "message": f"Failed writing resume: {exc}"}
                yield sse_event(event)
        except Exception as e:
            logger.exception("Streaming generation failed")
            yield sse_event({"stage": "error", "message": str(e)})

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=sse_headers)

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
