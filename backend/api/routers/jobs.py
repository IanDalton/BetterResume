import hashlib
import io
import logging
from fastapi import APIRouter, HTTPException
from typing import List

from api.utils import _validate_user_id, get_user_store
from utils.db_storage import DBStorage
from utils.legacy_migration import decode_legacy_info_row, decode_legacy_language_row
from utils.logging_utils import set_user_context
from api.schemas import JobUploadRequest, WORK_ENTRY_TYPES

logger = logging.getLogger("betterresume.api.jobs")
router = APIRouter()


def _divert_legacy_rows(storage: DBStorage, user_id: str, records: List[dict]) -> List[dict]:
    """Split incoming records into work-like rows and legacy info/language rows.

    Personal info and languages used to be smuggled through this same
    endpoint via type='info'/'language' (see utils/legacy_migration.py for
    the historical encoding). Rather than 400ing on those -- a stale cached
    frontend bundle could otherwise hard-fail a user's save, since frontend
    and backend deploy independently -- divert them to the dedicated
    profile/language tables and continue processing the rest as normal.
    Returns only the work-like records for the caller to keep processing.
    """
    work_records: List[dict] = []
    profile_fields: dict = {}
    links: List[dict] = []
    languages: List[dict] = []

    for rec in records:
        rec_type = (rec.get("type") or "").strip().lower()
        if rec_type == "info":
            decoded = decode_legacy_info_row(rec)
            if decoded is None:
                continue
            if decoded[0] == "profile_field":
                field, value = decoded[1]
                profile_fields[field] = value
            else:
                links.append(decoded[1])
        elif rec_type == "language":
            lang = decode_legacy_language_row(rec)
            if lang:
                languages.append(lang)
        else:
            work_records.append(rec)

    if profile_fields or links:
        existing_profile = storage.get_user_profile(user_id) or {}
        existing_links = storage.list_profile_links(user_id) if links else []
        storage.upsert_user_profile(
            user_id,
            full_name=profile_fields.get("full_name", existing_profile.get("full_name")),
            email=profile_fields.get("email", existing_profile.get("email")),
            phone=profile_fields.get("phone", existing_profile.get("phone")),
            address=profile_fields.get("address", existing_profile.get("address")),
        )
        if links:
            storage.replace_profile_links(user_id, existing_links + links)
        logger.info(
            "Diverted legacy info payload for user=%s (%d fields, %d links)",
            user_id, len(profile_fields), len(links),
        )

    if languages:
        existing_languages = storage.get_user_languages(user_id)
        storage.replace_user_languages(user_id, existing_languages + languages)
        logger.info("Diverted %d legacy language rows for user=%s", len(languages), user_id)

    return work_records


@router.post("/upload-jobs/{user_id}")
async def upload_jobs(user_id: str, payload: JobUploadRequest):
    """Accepts a JSON payload of work/education entry records and ingests them.

    Payload shape: {"jobs": [{type, company, description, role?, location?, start_date?, end_date?}, ...]}
    `type` must be one of WORK_ENTRY_TYPES; legacy 'info'/'language' rows are
    transitionally diverted to the profile/language tables (see
    _divert_legacy_rows) rather than rejected.
    """
    _validate_user_id(user_id)
    set_user_context(user_id)
    storage = DBStorage()
    storage._ensure_user(user_id)
    store = get_user_store(user_id)
    try:
        import pandas as pd

        all_records = [j.dict() for j in payload.jobs]
        records = _divert_legacy_rows(storage, user_id, all_records)

        unknown_types = {(r.get("type") or "").strip().lower() for r in records} - WORK_ENTRY_TYPES
        if unknown_types:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported entry type(s): {', '.join(sorted(unknown_types))}",
            )

        # Build DataFrame from JSON payload
        if not records:
            logger.info("Received empty (or fully-diverted) jobs payload for user=%s", user_id)
            # Still clear vectors and stored file
            try:
                await store.adelete_user_documents(user_id)
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
            await store.adelete_user_documents(user_id)
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
        await store.aadd_documents(
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
