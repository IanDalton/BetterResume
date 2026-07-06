"""One-time, idempotent backfill of legacy `type='info'`/`type='language'`
`job_experiences` rows into the dedicated `user_profile` / `user_profile_links`
/ `user_languages` tables.

Background: personal info (name/email/phone/address/website links) and
languages used to be stored as fake `job_experiences` rows that overloaded
the `company`/`description` columns meant for work experience (see
`api/routers/jobs.py` and the frontend's `services/csv.ts` for the historical
encoding). This module decodes that encoding and copies the data into its own
tables without ever deleting the source rows -- they're marked `migrated_at`
so type-filtering callers stop seeing them as current, but the original data
stays in place, auditable and reversible.

Idempotency: each legacy row's id is stored as `source_job_experience_id` on
the row it produces, with a UNIQUE constraint + `ON CONFLICT DO NOTHING` on
the insert. Re-running this after a partial failure (crash between writing a
row and marking it migrated) simply no-ops the already-written insert and
retries the mark -- no duplicates, no lost data.
"""

import logging
from typing import Any, Dict, Optional, Tuple

from utils.db_storage import DBStorage

logger = logging.getLogger("betterresume.legacy_migration")

_PERSONAL_FIELD_MAP = {
    "name": "full_name",
    "email": "email",
    "phone": "phone",
    "address": "address",
}
_SITE_KINDS = {"portfolio", "github", "linkedin", "twitter", "blog", "other"}


def decode_legacy_info_row(row: Dict[str, Any]) -> Optional[Tuple[str, Any]]:
    """Decode a legacy `type='info'` row.

    Returns ("profile_field", (field, value)) or ("link", {kind, label, url}),
    or None if the row's key isn't recognized (skipped, not an error).
    """
    key = (row.get("company") or "").strip().lower()
    desc = row.get("description") or ""
    if key in _PERSONAL_FIELD_MAP:
        return ("profile_field", (_PERSONAL_FIELD_MAP[key], desc.strip()))
    if key == "website":
        # csv.ts folds role_description onto a second line: "url\nlabel"
        lines = desc.split("\n", 1)
        url = lines[0].strip()
        label = lines[1].strip() if len(lines) > 1 else ""
        if not url:
            return None
        if label in _SITE_KINDS:
            kind, link_label = label, None
        elif label:
            kind, link_label = "other", label
        else:
            kind, link_label = "other", None
        return ("link", {"kind": kind, "label": link_label, "url": url})
    return None


def decode_legacy_language_row(row: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Decode a legacy `type='language'` row: role=name, description=proficiency."""
    name = (row.get("role") or row.get("company") or "").strip()
    if not name:
        return None
    return {"name": name, "proficiency": (row.get("description") or "").strip()}


def backfill_personal_info_and_languages(db: DBStorage, batch_size: int = 500) -> Dict[str, int]:
    """Migrate all not-yet-migrated legacy rows. Safe to call on every app boot."""
    stats = {"profile_fields": 0, "links": 0, "languages": 0, "skipped": 0, "errors": 0}
    sort_counters: Dict[str, int] = {}

    while True:
        rows = db.get_unmigrated_legacy_rows(limit=batch_size)
        if not rows:
            break
        for row in rows:
            row_id = row["id"]
            user_id = row["user_id"]
            row_type = (row.get("type") or "").strip().lower()
            try:
                if row_type == "info":
                    decoded = decode_legacy_info_row(row)
                    if decoded is None:
                        stats["skipped"] += 1
                    elif decoded[0] == "profile_field":
                        field, value = decoded[1]
                        db.upsert_profile_field_from_legacy(user_id, field, value)
                        stats["profile_fields"] += 1
                    else:
                        link = decoded[1]
                        order = sort_counters.get(f"link:{user_id}", 0)
                        db.insert_profile_link_from_legacy(
                            user_id, link["kind"], link["label"], link["url"], row_id, order
                        )
                        sort_counters[f"link:{user_id}"] = order + 1
                        stats["links"] += 1
                elif row_type == "language":
                    lang = decode_legacy_language_row(row)
                    if lang is None:
                        stats["skipped"] += 1
                    else:
                        order = sort_counters.get(f"lang:{user_id}", 0)
                        db.insert_language_from_legacy(
                            user_id, lang["name"], lang["proficiency"], row_id, order
                        )
                        sort_counters[f"lang:{user_id}"] = order + 1
                        stats["languages"] += 1
                else:
                    stats["skipped"] += 1
                db.mark_job_experience_migrated(row_id)
            except Exception:
                logger.exception("Failed to migrate legacy job_experience id=%s", row_id)
                stats["errors"] += 1
        if len(rows) < batch_size:
            break

    if any(stats.values()):
        logger.info("Legacy personal-info/language backfill complete: %s", stats)
    return stats
