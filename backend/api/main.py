import os
import logging
import hashlib
import json
# Disable telemetry noise from dependencies (e.g., ChromaDB / posthog)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "false")
os.environ.setdefault("POSTHOG_DISABLED", "1")
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from llm.chroma_db_tool import ChromaDBTool
import shutil
from bot import Bot
from resume import LatexResumeWriter, WordResumeWriter
from llm.gemini_tool import GeminiTool
from typing import Dict, Optional
import re
import time
import hmac
from hashlib import sha256

from utils.logging_utils import setup_logging, new_request_id, set_user_context, clear_request_id

DATA_DIR = os.getenv("DATA_DIR", "/app/data")  # default to mounted volume path
os.makedirs(DATA_DIR, exist_ok=True)
PERSIST_CHROMA = os.path.join(DATA_DIR, "chroma_db")
OUTPUTS_BASE = os.path.join(DATA_DIR, "outputs")
UPLOADS_BASE = os.path.join(DATA_DIR, "uploads")
for _d in (PERSIST_CHROMA, OUTPUTS_BASE, UPLOADS_BASE):
    os.makedirs(_d, exist_ok=True)
PROFILE_PICS_BASE = os.path.join(UPLOADS_BASE, "profile_pictures")
os.makedirs(PROFILE_PICS_BASE, exist_ok=True)

CACHE_FILENAME = "resume_cache.json"

ALLOWED_PROFILE_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/x-png": ".png",
}
PROFILE_EXTENSIONS = {".png", ".jpg"}

setup_logging()
app = FastAPI(title="BetterResume API", version="0.1.0")
# Module logger (relies on configured handlers)
logger = logging.getLogger("betterresume.api")
# Firebase auth disabled for now
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://iandalton.dev", "http://localhost", "http://127.0.0.1"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Maintain a cache of user_id -> ChromaDBTool (separate collections)
USER_TOOLS: Dict[str, ChromaDBTool] = {}

# Signing secret for secure download links
DOWNLOAD_SIGNING_SECRET = os.getenv("DOWNLOAD_SIGNING_SECRET") or os.getenv("SECRET_KEY") or "dev-secret-change-me"

def _hmac_sign(user_id: str, filename: str, exp: int) -> str:
    """Create an HMAC signature for a given user/file/expiry tuple."""
    message = f"{user_id}:{filename}:{exp}".encode("utf-8")
    return hmac.new(DOWNLOAD_SIGNING_SECRET.encode("utf-8"), message, sha256).hexdigest()

def make_signed_download_path(user_id: str, filename: str, ttl_seconds: int = 900) -> str:
    """Return a relative signed URL for downloading a file valid for ttl_seconds (default 15 minutes)."""
    exp = int(time.time()) + max(60, int(ttl_seconds))  # minimum 60s
    sig = _hmac_sign(user_id, filename, exp)
    # Keep relative path so the frontend can prefix with API base; include query string
    return f"/download/{user_id}/{filename}?exp={exp}&sig={sig}"


def _file_sha256(path: Optional[str]) -> Optional[str]:
    """Return the SHA256 hash for a file or None if unavailable."""
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        logger.exception("Failed computing hash for path=%s", path)
        return None


def _load_resume_cache(out_dir: str) -> Optional[dict]:
    cache_path = os.path.join(out_dir, CACHE_FILENAME)
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        logger.warning("Unable to read resume cache at %s", cache_path, exc_info=True)
        return None


def _save_resume_cache(out_dir: str, payload: dict) -> None:
    cache_path = os.path.join(out_dir, CACHE_FILENAME)
    tmp_path = cache_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp_path, cache_path)
    except Exception:
        logger.warning("Unable to persist resume cache to %s", cache_path, exc_info=True)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _build_result_signature(req: "ResumeRequest", csv_hash: Optional[str]) -> str:
    payload = {
        "job_description_hash": hashlib.sha256((req.job_description or "").encode("utf-8")).hexdigest(),
        "model": req.model,
        "csv_hash": csv_hash,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _build_request_signature(req: "ResumeRequest", csv_hash: Optional[str], profile_hash: Optional[str]) -> str:
    result_signature = _build_result_signature(req, csv_hash)
    payload = {
        "result_signature": result_signature,
        "format": req.format.lower(),
        "include_profile_picture": bool(req.include_profile_picture),
        "profile_hash": profile_hash if req.include_profile_picture else None,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _build_signed_files(user_id: str, fmt: str, out_dir: str) -> Dict[str, str]:
    files: Dict[str, str] = {}
    ext = ".tex" if fmt == "latex" else ".docx"
    source_name = f"resume{ext}"
    source_path = os.path.join(out_dir, source_name)
    if os.path.isfile(source_path):
        files["source"] = make_signed_download_path(user_id, source_name)
    pdf_path = os.path.join(out_dir, "resume.pdf")
    if os.path.isfile(pdf_path):
        files["pdf"] = make_signed_download_path(user_id, "resume.pdf")
    return files

def get_user_tool(user_id: str) -> ChromaDBTool:
    tool = USER_TOOLS.get(user_id)
    if tool is None:
        # Use per-user Chroma persist directory for hard isolation
        user_dir = os.path.join(PERSIST_CHROMA, f"user_{user_id}")
        os.makedirs(user_dir, exist_ok=True)
        # Also isolate by collection name per user to avoid any cross-collection leakage
        tool = ChromaDBTool(persist_directory=user_dir, collection_name=f"docs_{user_id}")
        USER_TOOLS[user_id] = tool
    else:
        # Migrate any pre-existing tool to per-user collection naming if it isn't already
        expected = f"docs_{user_id}"
        try:
            if getattr(tool, "collection_name", None) != expected:
                logger.info("Migrating collection for user=%s from %s to %s", user_id, tool.collection_name, expected)
                tool._client.delete_collection(tool.collection_name)  # type: ignore[attr-defined]
                tool.collection_name = expected
                tool._collection = tool._client.get_or_create_collection(name=expected)
        except Exception:
            pass
    return tool

def _validate_user_id(user_id: str):
    """Basic server-side guard to avoid shared/guessable collections.
    Allows only [A-Za-z0-9_-], length 8..128, and disallows literal 'guest'.
    """
    if user_id == "guest":
        raise HTTPException(status_code=400, detail="Invalid user id")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", user_id or ""):
        raise HTTPException(status_code=400, detail="Invalid user id format")


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    """Attach a correlation id to every request and basic access log lines."""
    rid = new_request_id()
    start = time.time()
    path = request.url.path
    method = request.method
    logger.info("Inbound request %s %s", method, path)
    try:
        response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)
        logger.info("Completed %s %s -> %s in %dms", method, path, getattr(response, 'status_code', '?'), duration_ms)
        return response
    finally:
        # Clear only the request id; user id is tied to the endpoint handling
        clear_request_id()

class ResumeRequest(BaseModel):
    job_description: str
    format: str = "latex"  # or "word"
    model: str = "gemini-2.5-flash"
    include_profile_picture: bool = False


def _resolve_profile_picture_path(user_id: str) -> Optional[str]:
    """Return the stored profile picture path for a user if present."""
    for ext in PROFILE_EXTENSIONS:
        candidate = os.path.join(PROFILE_PICS_BASE, f"profile_{user_id}{ext}")
        if os.path.isfile(candidate):
            return candidate
    return None

def clean_output_dir(path: str):
    """Remove all existing files in the user's output directory so only the newly generated resume remains.
    Keeps the directory itself (so any open file handles won't break directory existence).
    """
    try:
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            return
        for name in os.listdir(path):
            full = os.path.join(path, name)
            try:
                if os.path.isfile(full) or os.path.islink(full):
                    os.remove(full)
                elif os.path.isdir(full):
                    shutil.rmtree(full, ignore_errors=True)
            except Exception:
                # Best-effort; continue cleaning others
                pass
    except Exception:
        # Silently ignore; generation will overwrite needed files anyway
        pass

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/upload-jobs/{user_id}")
async def upload_jobs(user_id: str, file: UploadFile = File(...)):
    _validate_user_id(user_id)
    set_user_context(user_id)
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")
    contents = await file.read()
    logger.info("Uploading jobs CSV filename=%s size=%d bytes", file.filename, len(contents))
    new_hash = hashlib.sha256(contents).hexdigest()
    tmp_path = os.path.join(UPLOADS_BASE, f"uploaded_jobs_{user_id}.csv")
    hash_path = tmp_path + ".sha256"
    # If hash matches existing, skip re-ingestion
    """ if os.path.isfile(tmp_path) and os.path.isfile(hash_path):
        try:
            with open(hash_path, 'r', encoding='utf-8') as hf:
                old_hash = hf.read().strip()
            if old_hash == new_hash:
                # Attempt to get row count for informative response
                rows = None
                try:
                    import pandas as pd
                    df_prev = pd.read_csv(tmp_path)
                    rows = len(df_prev)
                except Exception:
                    pass
                return {"status": "unchanged", "rows_ingested": 0, "rows": rows, "hash": new_hash, "message": "CSV identical; ingestion skipped"}
        except Exception:
            pass """
    # Write new file
    with open(tmp_path, "wb") as f:
        f.write(contents)
    with open(hash_path, 'w', encoding='utf-8') as hf:
        hf.write(new_hash)
    tool = get_user_tool(user_id)
    try:
        import pandas as pd
        try:
            df = pd.read_csv(tmp_path)
        except Exception as e:
            logger.exception("Failed to parse uploaded CSV")
            raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {e}")
        # Minimum set: company, description, type (dates optional but normalize if present)
        required_min = {"company","description","type"}
        missing = sorted(list(required_min - set(df.columns)))
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required columns: {', '.join(missing)}")
        # Normalize date columns as strings in DD/MM/YYYY, preserve 'present'
        def _norm_date(val):
            try:
                if pd.isna(val):
                    return ''
            except Exception:
                pass
            s = str(val).strip()
            if not s:
                return ''
            sl = s.lower()
            if sl in ('present','current','now'):
                return 'present'
            import re as _re
            m = _re.match(r'^(\d{1,2})[\/-](\d{1,2})[\/-](\d{4})$', s)
            if m:
                dd = m.group(1).zfill(2); mm = m.group(2).zfill(2); yyyy = m.group(3)
                return f"{dd}/{mm}/{yyyy}"
            m = _re.match(r'^(\d{1,2})\/(\d{4})$', s)  # MM/YYYY
            if m:
                mm = m.group(1).zfill(2); yyyy = m.group(2)
                return f"01/{mm}/{yyyy}"
            m = _re.match(r'^(\d{4})[\/-](\d{1,2})$', s)  # YYYY/MM
            if m:
                yyyy = m.group(1); mm = m.group(2).zfill(2)
                return f"01/{mm}/{yyyy}"
            # leave as-is if cannot confidently parse
            return s
        for col in ["start_date","end_date"]:
            if col in df.columns:
                try:
                    df[col] = df[col].apply(_norm_date)
                except Exception:
                    pass
        # Persist normalized dates back to file for downstream readers
        try:
            df.to_csv(tmp_path, index=False)
        except Exception:
            pass
        rows = len(df)
        logger.info("Parsed CSV rows=%d; normalizing dates and updating user's collection", rows)
        from langchain_community.document_loaders.csv_loader import CSVLoader
        # Replace existing vectors for this user to avoid mixing across uploads
        logger.info("Using Chroma collection for user=%s: %s", user_id, tool.collection_name)
        try:
            tool._client.delete_collection(tool.collection_name)  # drop existing
            tool._collection = tool._client.get_or_create_collection(tool.collection_name)
        except Exception:
            # Fallback: if get_or_create is unavailable
            try:
                tool._collection = tool._client.get_collection(name=tool.collection_name)
            except Exception:
                tool._collection = tool._client.create_collection(name=tool.collection_name)
        data = CSVLoader(file_path=tmp_path).load()
        if not data:
            logger.info("CSV parsed but contains 0 rows; skipping Chroma ingest")
            return {"status": "ok", "rows_ingested": 0, "hash": new_hash}
        try:
            current = tool._collection.count()
        except Exception:
            current = 0
        logger.info("Ingesting %d rows into Chroma (existing=%d)", len(data), current)
        tool.add_documents(
            [d.page_content for d in data],
            [str(current + i) for i, _ in enumerate(data)],
        )
        logger.info("Ingestion complete; collection=%s new_count~%s", tool.collection_name, "?")
        return {"status": "ok", "rows_ingested": rows, "hash": new_hash}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during upload/ingest")
        raise HTTPException(status_code=500, detail=str(e))

def _resolve_user_jobs_csv(user_id: str) -> str:
    """Return absolute path to the uploaded jobs CSV for a user or raise HTTP 400 if missing."""
    _validate_user_id(user_id)
    csv_path = os.path.join(UPLOADS_BASE, f"uploaded_jobs_{user_id}.csv")
    if not os.path.isfile(csv_path):
        raise HTTPException(status_code=400, detail="Jobs CSV not uploaded. Upload via /upload-jobs/{user_id} first.")
    return csv_path


def _detect_profile_extension(file: UploadFile) -> Optional[str]:
    """Return a supported file extension for an uploaded profile picture or None if unsupported."""
    content_type = (file.content_type or "").lower()
    ext = ALLOWED_PROFILE_IMAGE_TYPES.get(content_type)
    if ext:
        return ext
    filename = (file.filename or "").lower()
    if filename:
        _, raw_ext = os.path.splitext(filename)
        if raw_ext in (".png", ".jpg", ".jpeg"):
            return ".jpg" if raw_ext == ".jpeg" else raw_ext
    return None


@app.post("/upload-profile-picture/{user_id}")
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


@app.get("/profile-picture/{user_id}")
async def get_profile_picture(user_id: str):
    _validate_user_id(user_id)
    set_user_context(user_id)
    path = _resolve_profile_picture_path(user_id)
    if not path:
        raise HTTPException(status_code=404, detail="Profile picture not found")
    return FileResponse(path)


@app.post("/generate-resume/{user_id}")
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
    profile_hash = _file_sha256(profile_path) if profile_path else None
    fmt = req.format.lower()
    result_signature = _build_result_signature(req, csv_hash)
    signature = _build_request_signature(req, csv_hash, profile_hash)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    cached = _load_resume_cache(out_dir)
    cached_signature = None
    cached_result_signature = None
    if cached:
        cached_signature = cached.get("render_signature") or cached.get("signature")
        cached_result_signature = cached.get("result_signature") or cached_signature
    files_from_cache = _build_signed_files(user_id, fmt, out_dir) if cached_signature == signature else {}
    cached_result = cached.get("result") if cached and cached_result_signature == result_signature else None
    if (
        cached
        and cached_signature == signature
        and cached.get("result") is not None
        and files_from_cache.get("source")
    ):
        logger.info("Reusing cached resume output for user_id=%s format=%s", user_id, fmt)
        return JSONResponse(content={"result": cached.get("result"), "files": files_from_cache, "rows": row_count})

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
            writer.write(cached_result, output=output_name, to_pdf=True)
        except Exception as exc:
            logger.exception("Failed rewriting resume from cache: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to render cached resume")
        signed_files = _build_signed_files(user_id, fmt, out_dir)
        if signed_files.get("source"):
            cache_payload = {
                "render_signature": signature,
                "result_signature": result_signature,
                "result": cached_result,
                "format": fmt,
                "model": req.model,
                "include_profile_picture": bool(req.include_profile_picture),
                "csv_hash": csv_hash,
                "profile_hash": profile_hash if req.include_profile_picture else None,
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
    clean_output_dir(out_dir)
    logger.info("Starting Bot generation; out_dir=%s", out_dir)
    bot = Bot(
        writer=writer,
        llm=GeminiTool(model=req.model),
        tool=tool,
        user_id=user_id,
        auto_ingest=True,
        jobs_csv=csv_path,
    )
    # Important: use absolute output base to avoid races due to process cwd changes
    abs_base = os.path.join(out_dir, "resume")
    result = bot.generate_resume(req.job_description, output_basename=abs_base)
    logger.info(
        "Bot generation complete; language=%s skills=%d exp=%d",
        result.get("language"),
        len(result.get("resume_section", {}).get("skills", [])),
        len(result.get("resume_section", {}).get("experience", [])),
    )
    signed_files = _build_signed_files(user_id, fmt, out_dir)
    if signed_files.get("source"):
        cache_payload = {
            "render_signature": signature,
            "result_signature": result_signature,
            "result": result,
            "format": fmt,
            "model": req.model,
            "include_profile_picture": bool(req.include_profile_picture),
            "csv_hash": csv_hash,
            "profile_hash": profile_hash,
            "generated_at": int(time.time()),
        }
        _save_resume_cache(out_dir, cache_payload)
    else:
        logger.warning("Resume generation completed but no source file found to cache for user_id=%s", user_id)
    return JSONResponse(content={"result": result, "files": signed_files, "rows": row_count})

def sse_event(data: dict) -> bytes:
    import json as _json
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

@app.post("/generate-resume-stream/{user_id}")
async def generate_resume_stream(user_id: str, req: ResumeRequest):
    _validate_user_id(user_id)
    set_user_context(user_id)
    """Stream progress events for resume generation via Server-Sent Events (SSE)."""
    csv_path = _resolve_user_jobs_csv(user_id)
    profile_path = _resolve_profile_picture_path(user_id) if req.include_profile_picture else None
    if req.include_profile_picture and not profile_path:
        logger.info("Profile picture requested but none stored for user=%s", user_id)
    csv_hash = _file_sha256(csv_path)
    profile_hash = _file_sha256(profile_path) if profile_path else None
    fmt = req.format.lower()
    result_signature = _build_result_signature(req, csv_hash)
    signature = _build_request_signature(req, csv_hash, profile_hash)
    tool = get_user_tool(user_id)
    out_dir = os.path.join(OUTPUTS_BASE, user_id)
    os.makedirs(out_dir, exist_ok=True)
    cached = _load_resume_cache(out_dir)
    cached_signature = None
    cached_result_signature = None
    if cached:
        cached_signature = cached.get("render_signature") or cached.get("signature")
        cached_result_signature = cached.get("result_signature") or cached_signature
    cached_files = _build_signed_files(user_id, fmt, out_dir) if cached_signature == signature else {}
    cached_result = cached.get("result") if cached and cached_result_signature == result_signature else None
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

    if (
        cached
        and cached_signature == signature
        and cached.get("result") is not None
        and cached_files.get("source")
    ):
        logger.info("Reusing cached streaming resume for user_id=%s format=%s", user_id, fmt)

        def cached_event_generator():
            try:
                yield sse_event({"stage": "csv_info", "rows": row_count, "collection": collection, "docs": col_docs})
                yield sse_event({"stage": "cached", "message": "Using cached resume output"})
                yield sse_event({
                    "stage": "done",
                    "message": "Resume generation complete",
                    "result": cached.get("result"),
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
                writer.write(cached_result, output=output_name, to_pdf=True)
                files = _build_signed_files(user_id, fmt, out_dir)
                if files.get("source"):
                    cache_payload = {
                        "render_signature": signature,
                        "result_signature": result_signature,
                        "result": cached_result,
                        "format": fmt,
                        "model": req.model,
                        "include_profile_picture": bool(req.include_profile_picture),
                        "csv_hash": csv_hash,
                        "profile_hash": profile_hash if req.include_profile_picture else None,
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
    bot = Bot(
        writer=writer,
        llm=GeminiTool(model=req.model),
        tool=tool,
        user_id=user_id,
        auto_ingest=True,
        jobs_csv=csv_path,
    )

    def event_generator():
        try:
            # Send initial CSV info event
            yield sse_event({"stage": "csv_info", "rows": row_count, "collection": collection, "docs": col_docs})
            abs_base = os.path.join(out_dir, "resume")
            for event in bot.generate_resume_progress(req.job_description, output_basename=abs_base):
                # Normalize final file paths for client (match non-stream endpoint style)
                if event.get("stage") == "done":
                    files = _build_signed_files(user_id, fmt, out_dir)
                    event["files"] = files
                    if files.get("source"):
                        cache_payload = {
                            "render_signature": signature,
                            "result_signature": result_signature,
                            "result": event.get("result"),
                            "format": fmt,
                            "model": req.model,
                            "include_profile_picture": bool(req.include_profile_picture),
                            "csv_hash": csv_hash,
                            "profile_hash": profile_hash,
                            "generated_at": int(time.time()),
                        }
                        _save_resume_cache(out_dir, cache_payload)
                    else:
                        logger.warning("Streaming generation done but source missing for caching user_id=%s", user_id)
                yield sse_event(event)
        except Exception as e:
            logger.exception("Streaming generation failed")
            yield sse_event({"stage": "error", "message": str(e)})

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=sse_headers)

@app.get("/download/{user_id}/{filename}")
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

@app.get("/users")
async def list_users():
    return {"users": list(USER_TOOLS.keys())}

@app.delete("/users/{user_id}")
async def clear_user(user_id: str):
    _validate_user_id(user_id)
    set_user_context(user_id)
    # Drop the user's collection and remove cache entry
    if user_id not in USER_TOOLS:
        raise HTTPException(status_code=404, detail="User not found")
    tool = USER_TOOLS.pop(user_id)
    try:
        tool._client.delete_collection(tool.collection_name)  # type: ignore[attr-defined]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete collection: {e}")
    return {"status": "deleted", "user_id": user_id}

# Convenience root
@app.get("/")
async def root():
    return {"message": "BetterResume API. Use /upload-jobs/{user_id} then /generate-resume/{user_id}."}
