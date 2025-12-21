import os
import hashlib
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException
from langchain_community.document_loaders.csv_loader import CSVLoader

from api.config import UPLOADS_BASE
from api.utils import _validate_user_id, get_user_tool
from utils.logging_utils import set_user_context

logger = logging.getLogger("betterresume.api.jobs")
router = APIRouter()

@router.post("/upload-jobs/{user_id}")
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
        
        # Replace existing vectors for this user to avoid mixing across uploads
        logger.info("Using pgvector for user=%s", user_id)
        try:
            tool.delete_user_documents(user_id)
        except Exception:
            pass
        data = CSVLoader(file_path=tmp_path).load()
        if not data:
            logger.info("CSV parsed but contains 0 rows; skipping ingest")
            return {"status": "ok", "rows_ingested": 0, "hash": new_hash}
        ids = [f"{user_id}_{i}" for i in range(len(data))]
        logger.info("Ingesting %d rows into pgvector for user=%s", len(data), user_id)
        tool.add_documents(
            [d.page_content for d in data],
            ids,
            user_id=user_id,
        )
        logger.info("Ingestion complete for user=%s", user_id)
        return {"status": "ok", "rows_ingested": rows, "hash": new_hash}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during upload/ingest")
        raise HTTPException(status_code=500, detail=str(e))
