import os
import time
import hmac
import hashlib
import json
import re
import shutil
import logging
from hashlib import sha256
from typing import Optional, Dict
from fastapi import HTTPException, UploadFile

from api.config import (
    DOWNLOAD_SIGNING_SECRET,
    CACHE_FILENAME,
    PROFILE_PICS_BASE,
    PROFILE_EXTENSIONS,
    ALLOWED_PROFILE_IMAGE_TYPES,
    UPLOADS_BASE,
    OUTPUTS_BASE
)
from api.state import USER_TOOLS
from llm.pg_vector_tool import PGVectorTool

logger = logging.getLogger("betterresume.api.utils")

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

def _normalize_resume_cache(raw: Optional[dict]) -> dict:
    """Return a cache dictionary that always exposes `results` and `renders` maps."""
    normalized: dict = {"results": {}, "renders": {}}
    if not isinstance(raw, dict):
        return normalized

    # Already using the new structure – ensure mandatory containers exist.
    if "results" in raw or "renders" in raw:
        raw.setdefault("results", {})
        raw.setdefault("renders", {})
        return raw

    legacy_result_sig = raw.get("result_signature") or raw.get("signature")
    legacy_render_sig = raw.get("render_signature") or raw.get("signature")
    legacy_result = raw.get("result")

    if legacy_result_sig and legacy_result is not None:
        normalized["results"][legacy_result_sig] = {
            "result": legacy_result,
            "model": raw.get("model"),
            "csv_hash": raw.get("csv_hash"),
            "job_description_hash": raw.get("job_description_hash"),
            "generated_at": raw.get("generated_at"),
        }

    if legacy_render_sig and legacy_result_sig:
        normalized["renders"][legacy_render_sig] = {
            "result_signature": legacy_result_sig,
            "format": raw.get("format"),
            "include_profile_picture": raw.get("include_profile_picture"),
            "profile_hash": raw.get("profile_hash"),
            "generated_at": raw.get("generated_at"),
        }

    # Preserve legacy top-level keys so future saves continue overwriting them.
    normalized.update(
        {
            "result_signature": legacy_result_sig,
            "render_signature": legacy_render_sig,
            "result": legacy_result,
            "format": raw.get("format"),
            "include_profile_picture": raw.get("include_profile_picture"),
            "csv_hash": raw.get("csv_hash"),
            "model": raw.get("model"),
            "job_description_hash": raw.get("job_description_hash"),
            "profile_hash": raw.get("profile_hash"),
        }
    )
    return normalized

def _load_resume_cache(out_dir: str) -> Optional[dict]:
    cache_path = os.path.join(out_dir, CACHE_FILENAME)
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            return _normalize_resume_cache(json.load(fh))
    except Exception:
        logger.warning("Unable to read resume cache at %s", cache_path, exc_info=True)
        return None

def _save_resume_cache(out_dir: str, payload: dict) -> None:
    cache_path = os.path.join(out_dir, CACHE_FILENAME)
    tmp_path = cache_path + ".tmp"
    existing = _load_resume_cache(out_dir) or {"results": {}, "renders": {}}
    result_signature = payload.get("result_signature") or payload.get("signature")
    render_signature = payload.get("render_signature") or payload.get("signature")
    result_body = payload.get("result")
    generated_at = payload.get("generated_at") or int(time.time())

    if result_signature and result_body is not None:
        existing.setdefault("results", {})[result_signature] = {
            "result": result_body,
            "model": payload.get("model"),
            "csv_hash": payload.get("csv_hash"),
            "job_description_hash": payload.get("job_description_hash"),
            "generated_at": generated_at,
        }

    if render_signature and result_signature:
        existing.setdefault("renders", {})[render_signature] = {
            "result_signature": result_signature,
            "format": payload.get("format"),
            "include_profile_picture": payload.get("include_profile_picture"),
            "profile_hash": payload.get("profile_hash"),
            "generated_at": generated_at,
        }

    # Maintain legacy top-level keys for compatibility with any older readers.
    existing.update(
        {
            "result_signature": result_signature,
            "render_signature": render_signature,
            "result": result_body if result_body is not None else existing.get("result"),
            "format": payload.get("format"),
            "include_profile_picture": payload.get("include_profile_picture"),
            "csv_hash": payload.get("csv_hash"),
            "model": payload.get("model"),
            "job_description_hash": payload.get("job_description_hash"),
            "profile_hash": payload.get("profile_hash"),
        }
    )
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, ensure_ascii=False)
        os.replace(tmp_path, cache_path)
    except Exception:
        logger.warning("Unable to persist resume cache to %s", cache_path, exc_info=True)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

def _hash_text(value: Optional[str]) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()

def _build_result_signature(req, csv_hash: Optional[str], job_hash: str) -> str:
    payload = {
        "job_description_hash": job_hash,
        "model": req.model,
        "csv_hash": csv_hash,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

def _build_request_signature(
    req, csv_hash: Optional[str], profile_hash: Optional[str], job_hash: str
) -> str:
    result_signature = _build_result_signature(req, csv_hash, job_hash)
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

def get_user_tool(user_id: str) -> PGVectorTool:
    tool = USER_TOOLS.get(user_id)
    if tool is None:
        # Create a per-user PGVectorTool instance (user isolation via user_id column)
        tool = PGVectorTool(db_url=os.getenv("DATABASE_URL"), user_id=user_id)
        USER_TOOLS[user_id] = tool
    else:
        # Ensure user_id is set on existing tool
        try:
            if getattr(tool, "user_id", None) != user_id:
                tool.user_id = user_id
        except Exception:
            pass
    return tool

def _validate_user_id(user_id: str):
    """Basic server-side guard to avoid shared/guessable collections."""
    if user_id == "guest":
        raise HTTPException(status_code=400, detail="Invalid user id")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", user_id or ""):
        raise HTTPException(status_code=400, detail="Invalid user id format")

def _resolve_profile_picture_path(user_id: str) -> Optional[str]:
    """Return the stored profile picture path for a user if present."""
    for ext in PROFILE_EXTENSIONS:
        candidate = os.path.join(PROFILE_PICS_BASE, f"profile_{user_id}{ext}")
        if os.path.isfile(candidate):
            return candidate
    return None

def clean_output_dir(path: str):
    """Remove all existing files in the user's output directory."""
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
                pass
    except Exception:
        pass

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

def sse_event(data: dict) -> bytes:
    import json as _json
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
