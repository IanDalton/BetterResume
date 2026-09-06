import os
import time
import logging
import hmac
from typing import Optional
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import ValidationError

from api.config import IMPORT_PDF_MAX_BYTES, OUTPUTS_BASE
from api.schemas import ResumeAnalysisRequest, ResumeRequest
from api.utils import (
    _validate_user_id,
    _resolve_user_jobs_csv,
    _resolve_profile_picture_path,
    _file_sha256,
    _hash_text,
    _hash_profile,
    _build_result_signature,
    _build_request_signature,
    _load_resume_cache,
    _build_signed_files,
    _make_writer,
    clean_output_dir,
    _save_resume_cache,
    get_profile_with_links,
    get_user_store,
    sse_event,
    SSE_HEADERS,
    _hmac_sign
)
from utils.logging_utils import set_user_context
from utils.db_storage import DBStorage

from bot import Bot
from llm import agent
from llm.resume_analysis import ResumeAnalysis, analyze_resume
from models.resume import ResumeOutputFormat
from utils.imported_resume import NoExperienceError, imported_to_resume
from utils.resume_import import ResumePdfEmptyError, parse_resume_pdf

logger = logging.getLogger("betterresume.api.resume")
router = APIRouter()


def _record_generation(user_id, model, fmt, language, started_at, status, error=None,
                        requested_model=None, fallback_used=False):
    """Persist a generation event for admin statistics; never raises."""
    try:
        DBStorage().record_generation_event(
            user_id=user_id,
            model=str(model or ""),
            requested_model=str(requested_model or "") or None,
            format=fmt,
            language=language,
            duration_ms=int((time.time() - started_at) * 1000),
            status=status,
            error=error,
            fallback_used=bool(fallback_used),
        )
    except Exception:
        logger.warning("Failed to record generation event for user_id=%s", user_id, exc_info=True)


def _record_analysis(user_id: str, analysis: ResumeAnalysis, source: str, started_at: float):
    """Persist one `resume_analyses` row for admin statistics; never raises.
    A generated resume is attributed to the model that served the user's
    latest successful generation."""
    try:
        storage = DBStorage()
        generation_model = storage.get_latest_generation_model(user_id) if source == "generated" else None
        scores = analysis.review.scores if analysis.review else None
        storage.record_resume_analysis(
            user_id=user_id,
            source=source,
            generation_model=generation_model,
            review_model=analysis.model,
            ats_score=analysis.ats.score,
            keyword_coverage=analysis.ats.keyword_coverage,
            review_overall=scores.overall if scores else None,
            review_relevance=scores.relevance if scores else None,
            review_quality=scores.quality if scores else None,
            review_coherence=scores.coherence if scores else None,
            review_error=analysis.review_error,
            duration_ms=int((time.time() - started_at) * 1000),
        )
    except Exception:
        logger.warning("Failed to record resume analysis for user_id=%s", user_id, exc_info=True)


def _prepare_request(user_id: str, req: ResumeRequest, csv_path: str, profile_path):
    """Shared per-request fingerprinting for both generation endpoints: fetch
    the profile dict (for the writers and the profile-fields cache buster),
    record the request, and compute the content hashes and cache signatures.
    Returns (profile_dict, csv_hash, job_hash, profile_hash, fmt,
    result_signature, signature)."""
    profile_dict = get_profile_with_links(user_id)
    csv_hash = _file_sha256(csv_path)
    job_hash = _hash_text(req.job_description)
    _record_resume_request(user_id, req.job_description)
    profile_hash = _file_sha256(profile_path) if profile_path else None
    fmt = req.format.lower()
    result_signature = _build_result_signature(req, csv_hash, job_hash)
    signature = _build_request_signature(req, csv_hash, profile_hash, job_hash, _hash_profile(profile_dict))
    return profile_dict, csv_hash, job_hash, profile_hash, fmt, result_signature, signature


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


def _cache_payload(req: ResumeRequest, fmt, result, signature, result_signature, csv_hash, profile_hash, job_hash, model):
    """`model` must be the effective generation model for this specific result --
    `bot.generation_model` when a `Bot` produced it, or the model already stored
    against `result_signature` when we're only re-rendering a cache hit. Never
    re-derive it from `agent.DEFAULT_MODEL`: that import-time constant is stale
    the moment the model becomes runtime-configurable (see `_build_result_signature`)."""
    return {
        "render_signature": signature,
        "result_signature": result_signature,
        "result": _serialize_result(result),
        "format": fmt,
        "model": model,
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
    logger.info("Generate resume requested; format=%s model=%s", req.format, agent.get_effective_model("generation"))
    csv_path = _resolve_user_jobs_csv(user_id)
    logger.info("Resolved jobs CSV for user_id=%s at %s", user_id, csv_path)
    row_count = _count_csv_rows(csv_path)
    if not row_count:
        raise HTTPException(status_code=400, detail="No jobs found. Please upload your entries before generating.")
    profile_path = _resolve_profile_picture_path(user_id) if req.include_profile_picture else None
    if req.include_profile_picture and not profile_path:
        logger.info("Profile picture requested but none stored for user=%s", user_id)
    profile_dict, csv_hash, job_hash, profile_hash, fmt, result_signature, signature = _prepare_request(
        user_id, req, csv_path, profile_path
    )
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
        writer = _make_writer(fmt, csv_path, profile_path, profile_dict)
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
                model=result_entry.get("model") if result_entry else agent.get_effective_model("generation"),
            ))
        return JSONResponse(content={"result": cached_result, "files": signed_files, "rows": row_count})

    writer = _make_writer(fmt, csv_path, profile_path, profile_dict)
    store = get_user_store(user_id)
    clean_output_dir(out_dir)
    logger.info("Starting Bot generation; out_dir=%s", out_dir)
    bot = Bot(user_id=user_id, vector_store=store, jobs_csv=csv_path)
    gen_start = time.time()
    try:
        result = await bot.generate_resume(req.job_description, improvements=req.improvements)
    except Exception as exc:
        _record_generation(
            user_id, bot.last_generation_model or bot.generation_model, fmt, None, gen_start, "error", str(exc),
            requested_model=bot.generation_model, fallback_used=bot.last_generation_fallback_used,
        )
        raise
    _record_generation(
        user_id, bot.last_generation_model or bot.generation_model, fmt, result.language, gen_start, "success",
        requested_model=bot.generation_model, fallback_used=bot.last_generation_fallback_used,
    )
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
            model=bot.generation_model,
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
    profile_dict, csv_hash, job_hash, profile_hash, fmt, result_signature, signature = _prepare_request(
        user_id, req, csv_path, profile_path
    )
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
                writer = _make_writer(fmt, csv_path, profile_path, profile_dict)
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
                        model=result_entry.get("model") if result_entry else agent.get_effective_model("generation"),
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

    writer = _make_writer(fmt, csv_path, profile_path, profile_dict)
    clean_output_dir(out_dir)
    logger.info(
        "Starting streaming generation; format=%s model=%s out_dir=%s",
        req.format, agent.get_effective_model("generation"), out_dir,
    )
    bot = Bot(user_id=user_id, vector_store=store, jobs_csv=csv_path)

    async def event_generator():
        gen_start = time.time()
        try:
            yield sse_event(csv_info)
            async for event in bot.generate_resume_progress(req.job_description, improvements=req.improvements):
                if event.get("stage") == "done":
                    # Write files here, based on final result
                    output_name = os.path.join(out_dir, f"resume{writer.file_ending}")
                    try:
                        result_obj = event.get("result")
                        _record_generation(
                            user_id, bot.last_generation_model or bot.generation_model, fmt,
                            getattr(result_obj, "language", None), gen_start, "success",
                            requested_model=bot.generation_model, fallback_used=bot.last_generation_fallback_used,
                        )
                        writer.write(result_obj, output=output_name, to_pdf=True)
                        files = _build_signed_files(user_id, fmt, out_dir)
                        event["files"] = files
                        event["result"] = _serialize_result(result_obj)
                        if files.get("source"):
                            _save_resume_cache(out_dir, _cache_payload(
                                req, fmt, result_obj, signature, result_signature, csv_hash, profile_hash, job_hash,
                                model=bot.generation_model,
                            ))
                        else:
                            logger.warning("Streaming generation done but source missing for caching user_id=%s", user_id)
                    except Exception as exc:
                        logger.exception("Streaming: file write failed: %s", exc)
                        event = {"stage": "error", "message": f"Failed writing resume: {exc}"}
                yield sse_event(event)
        except Exception as e:
            logger.exception("Streaming generation failed")
            _record_generation(
                user_id, bot.last_generation_model or bot.generation_model, fmt, None, gen_start, "error", str(e),
                requested_model=bot.generation_model, fallback_used=bot.last_generation_fallback_used,
            )
            yield sse_event({"stage": "error", "message": str(e)})

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/analyze-resume/{user_id}")
async def analyze_resume_endpoint(user_id: str, req: ResumeAnalysisRequest):
    """ATS score plus LLM review of a generated resume against its job
    description. Stateless: the client sends back the `result` it received
    from generation, so nothing has to be looked up in the render cache."""
    _validate_user_id(user_id)
    set_user_context(user_id)
    if not req.job_description or not req.job_description.strip():
        raise HTTPException(status_code=400, detail="A job description is required to analyze the resume")
    try:
        resume = ResumeOutputFormat.model_validate(req.resume)
    except ValidationError as exc:
        logger.info("Rejected resume payload for analysis: %s", exc.errors()[:3])
        raise HTTPException(status_code=422, detail="Invalid resume payload")
    started = time.time()
    analysis = await analyze_resume(resume, req.job_description, language=req.language)
    _log_analysis(analysis, started)
    _record_analysis(user_id, analysis, "generated", started)
    return JSONResponse(content=analysis.model_dump())


def _log_analysis(analysis: ResumeAnalysis, started: float) -> None:
    logger.info(
        "Resume analysis complete; ats=%d review=%s model=%s duration_ms=%d",
        analysis.ats.score, "ok" if analysis.review else f"failed ({analysis.review_error})",
        analysis.model, int((time.time() - started) * 1000),
    )


@router.post("/analyze-resume-pdf/{user_id}")
async def analyze_resume_pdf_endpoint(
    user_id: str,
    file: UploadFile = File(...),
    job_description: str = Form(...),
    language: Optional[str] = Form(None),
):
    """ATS score plus LLM review of an existing resume PDF (any resume, including
    a LinkedIn export) against a job description, without generating one.
    The PDF goes through the same parser as the import flow; nothing is saved
    to the user's profile. The response is the analysis plus the parsed
    `resume` it was computed on and the parser's `warnings`."""
    _validate_user_id(user_id)
    set_user_context(user_id)
    if not job_description or not job_description.strip():
        raise HTTPException(status_code=400, detail="A job description is required to analyze the resume")
    content_type = (file.content_type or "").lower()
    if content_type != "application/pdf" and not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload your resume as a PDF file.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")
    if len(content) > IMPORT_PDF_MAX_BYTES:
        raise HTTPException(status_code=400, detail="PDF too large (max 10 MB)")

    started = time.time()
    try:
        parsed = await parse_resume_pdf(content)
    except ResumePdfEmptyError as exc:
        raise HTTPException(
            status_code=422,
            detail="No readable text found in this PDF. Upload a text-based PDF (not a scan).",
        ) from exc
    except Exception as exc:
        logger.exception("Resume PDF parsing failed for analysis user=%s", user_id)
        raise HTTPException(status_code=502, detail="Could not read this PDF right now. Please try again.") from exc
    try:
        resume = imported_to_resume(parsed, language=language or "en")
    except NoExperienceError as exc:
        raise HTTPException(status_code=422, detail="No work experience was found in this PDF, so there is nothing to score.") from exc

    analysis = await analyze_resume(resume, job_description, language=language)
    _log_analysis(analysis, started)
    _record_analysis(user_id, analysis, "imported", started)
    return JSONResponse(content={
        **analysis.model_dump(),
        "resume": resume.model_dump(),
        "warnings": list(parsed.warnings or []),
    })


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
