import hashlib
import io
import logging
from fastapi import APIRouter, HTTPException
from typing import List

from api.utils import _validate_user_id, get_user_tool
from utils.db_storage import DBStorage
from utils.logging_utils import set_user_context
from api.schemas import JobUploadRequest

logger = logging.getLogger("betterresume.api.jobs")
router = APIRouter()

@router.post("/upload-jobs/{user_id}")
async def upload_jobs(user_id: str, payload: JobUploadRequest):
    """Accepts a JSON payload of job/entry records and ingests them.

    Payload shape: {"jobs": [{type, company, description, role?, location?, start_date?, end_date?}, ...]}
    """
    _validate_user_id(user_id)
    set_user_context(user_id)
    storage = DBStorage()
    tool = get_user_tool(user_id)
    try:
        import pandas as pd
        # Build DataFrame from JSON payload
        if not payload.jobs:
            logger.info("Received empty jobs payload for user=%s", user_id)
            # Still clear vectors and stored file
            try:
                await tool.adelete_user_documents(user_id)
            except Exception:
                pass
            # Persist empty CSV
            empty_df = pd.DataFrame(columns=["type","company","location","role","start_date","end_date","description"])  # noqa: E501
            normalized_csv = empty_df.to_csv(index=False).encode("utf-8")
            new_hash = hashlib.sha256(normalized_csv).hexdigest()
            storage.save_file(
                user_id=user_id,
                file_type="jobs_csv",
                content=normalized_csv,
                filename=f"jobs_{user_id}.csv",
                mime_type="text/csv",
            )
            storage.replace_job_experiences(user_id, [])
            return {"status": "ok", "rows_ingested": 0, "hash": new_hash}

        # Convert list of models to dicts
        records = [j.dict() for j in payload.jobs]
        df = pd.DataFrame.from_records(records)

        # Minimum set: company, description, type (dates optional but normalize if present)
        required_min = {"company", "description", "type"}
        missing = sorted(list(required_min - set(df.columns)))
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")

        # Normalize date columns as strings in DD/MM/YYYY, preserve 'present'
        def _norm_date(val):
            try:
                if pd.isna(val):
                    return ""
            except Exception:
                pass
            s = str(val).strip()
            if not s:
                return ""
            sl = s.lower()
            if sl in ("present", "current", "now"):
                return "present"
            import re as _re
            m = _re.match(r"^(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$", s)
            if m:
                dd = m.group(1).zfill(2)
                mm = m.group(2).zfill(2)
                yyyy = m.group(3)
                return f"{dd}/{mm}/{yyyy}"
            m = _re.match(r"^(\d{1,2})\/(\d{4})$", s)  # MM/YYYY
            if m:
                mm = m.group(1).zfill(2)
                yyyy = m.group(2)
                return f"01/{mm}/{yyyy}"
            m = _re.match(r"^(\d{4})[\/\-](\d{1,2})$", s)  # YYYY/MM
            if m:
                yyyy = m.group(1)
                mm = m.group(2).zfill(2)
                return f"01/{mm}/{yyyy}"
            # leave as-is if cannot confidently parse
            return s

        for col in ["start_date", "end_date"]:
            if col in df.columns:
                try:
                    df[col] = df[col].apply(_norm_date)
                except Exception:
                    pass

        # Ensure consistent column ordering for CSV materialization used downstream
        for col in ["location", "role", "start_date", "end_date"]:
            if col not in df.columns:
                df[col] = ""
        ordered_cols = ["type", "company", "location", "role", "start_date", "end_date", "description"]
        df = df[ordered_cols]

        normalized_csv = df.to_csv(index=False).encode("utf-8")
        new_hash = hashlib.sha256(normalized_csv).hexdigest()

        # Persist CSV blob and structured rows in Postgres (CSV keeps the rest of the system unchanged)
        storage.save_file(
            user_id=user_id,
            file_type="jobs_csv",
            content=normalized_csv,
            filename=f"jobs_{user_id}.csv",
            mime_type="text/csv",
        )
        storage.replace_job_experiences(user_id, df.to_dict(orient="records"))
        rows = len(df)
        logger.info("Parsed JSON jobs=%d; normalized and stored as CSV in database", rows)

        # Replace existing vectors for this user to avoid mixing across uploads
        logger.info("Using pgvector for user=%s", user_id)
        try:
            await tool.adelete_user_documents(user_id)
        except Exception:
            pass
        if rows == 0:
            logger.info("Jobs parsed but contains 0 rows; skipping ingest")
            return {"status": "ok", "rows_ingested": 0, "hash": new_hash}
        df_ingest = df.fillna("")
        docs = []
        for _, row in df_ingest.iterrows():
            docs.append("\n".join([f"{col}: {row[col]}" for col in df_ingest.columns]))
        ids = [f"{user_id}_{i}" for i in range(len(docs))]
        logger.info("Ingesting %d rows into pgvector for user=%s", len(docs), user_id)
        await tool.aadd_documents(
            docs,
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
