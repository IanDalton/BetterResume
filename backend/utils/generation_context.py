"""Builds an authoritative context block injected into the generation prompt.

Resume audits flagged three recurring LLM failures: future/garbled dates,
years-of-experience claims that don't match the stored work history, and no
knowledge of the user's spoken languages. This module derives all three facts
deterministically from the stored job_experiences records so the model is
anchored to reality instead of guessing.
"""

import logging
import re
from datetime import date
from typing import List, Optional, Tuple

logger = logging.getLogger("betterresume.generation_context")

# Entry types that count as professional experience for the years-of-experience total
WORK_TYPES = {"job", "contract", "part-time", "non-profit"}

# Independent/short engagements that should be consolidated into one grouped
# resume entry when there are many of them, instead of cluttering the timeline
GROUPABLE_TYPES = {"contract", "part-time", "project", "non-profit"}

# At this many independent engagements the context tells the model to group them
GROUPING_THRESHOLD = 3

LANGUAGE_TYPE = "language"

_PRESENT_TOKENS = {"present", "current", "now", "actual"}


def parse_stored_date(value: Optional[str], today: date) -> Optional[date]:
    """Parse the date strings stored in job_experiences (DD/MM/YYYY, MM/YYYY, YYYY or 'present')."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.lower() in _PRESENT_TOKENS:
        return today
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        _, mm, yyyy = m.groups()
        try:
            return date(int(yyyy), int(mm), 1)
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)
    if m:
        mm, yyyy = m.groups()
        try:
            return date(int(yyyy), int(mm), 1)
        except ValueError:
            return None
    m = re.match(r"^(\d{4})$", s)
    if m:
        return date(int(s), 1, 1)
    return None


def _work_intervals(records: List[dict], today: date) -> List[Tuple[date, date]]:
    intervals = []
    for rec in records or []:
        if str(rec.get("type", "")).strip().lower() not in WORK_TYPES:
            continue
        start = parse_stored_date(rec.get("start_date"), today)
        end = parse_stored_date(rec.get("end_date"), today) or (start and today)
        if start is None or end is None:
            continue
        # Clamp future-dated entries instead of letting them inflate the total
        start = min(start, today)
        end = min(end, today)
        if end >= start:
            intervals.append((start, end))
    return intervals


def compute_total_experience_months(records: List[dict], today: Optional[date] = None) -> int:
    """Total months of professional experience, with overlapping roles merged."""
    today = today or date.today()
    intervals = sorted(_work_intervals(records, today))
    if not intervals:
        return 0
    total = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += _months_between(cur_start, cur_end)
            cur_start, cur_end = start, end
    total += _months_between(cur_start, cur_end)
    return total


def _months_between(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def format_experience_duration(months: int) -> str:
    years, rem = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if rem or not parts:
        parts.append(f"{rem} month{'s' if rem != 1 else ''}")
    return " ".join(parts)


def format_display_date(value: Optional[str], today: Optional[date] = None) -> str:
    """Stored DB date string -> resume display format (MM/YYYY, 'Present', or as-is)."""
    s = str(value).strip() if value else ""
    if not s:
        return ""
    if s.lower() in _PRESENT_TOKENS:
        return "Present"
    if re.match(r"^\d{4}$", s):
        return s
    parsed = parse_stored_date(s, today or date.today())
    return parsed.strftime("%m/%Y") if parsed else s


def summarize_groupable_engagements(
    records: List[dict], today: Optional[date] = None
) -> Tuple[int, Optional[Tuple[date, date]]]:
    """Count contract/part-time/project/volunteer engagements and their overall span."""
    today = today or date.today()
    count = 0
    starts: List[date] = []
    ends: List[date] = []
    for rec in records or []:
        if str(rec.get("type", "")).strip().lower() not in GROUPABLE_TYPES:
            continue
        count += 1
        start = parse_stored_date(rec.get("start_date"), today)
        end = parse_stored_date(rec.get("end_date"), today) or (start and today)
        if start:
            starts.append(min(start, today))
        if end:
            ends.append(min(end, today))
    span = (min(starts), max(ends)) if starts and ends else None
    return count, span


def extract_languages(records: List[dict]) -> List[Tuple[str, str]]:
    """(name, proficiency) pairs from records with type='language'.

    Language entries store the language name in `role` and the proficiency in
    `description` (matching the generic CSV schema).
    """
    languages = []
    for rec in records or []:
        if str(rec.get("type", "")).strip().lower() != LANGUAGE_TYPE:
            continue
        name = (rec.get("role") or rec.get("company") or "").strip()
        proficiency = (rec.get("description") or "").strip()
        if name:
            languages.append((name, proficiency))
    return languages


def build_generation_context(records: List[dict], today: Optional[date] = None) -> str:
    """Render the authoritative context block appended to the generation prompt."""
    today = today or date.today()
    lines = [
        "AUTHORITATIVE USER CONTEXT (computed from the user's stored data; the resume MUST be consistent with it):",
        f"- Today's date is {today.strftime('%m/%Y')}. Never output a start or end date after this date. "
        "Roles that are still ongoing must use 'Present' as the end date.",
    ]

    months = compute_total_experience_months(records, today)
    if months > 0:
        lines.append(
            f"- The user's total professional experience, computed from their stored work history "
            f"(overlapping roles merged), is {format_experience_duration(months)}. Any years-of-experience "
            "claim in the professional summary must match this figure; never round up or overstate it."
        )

    engagement_count, span = summarize_groupable_engagements(records, today)
    if engagement_count >= GROUPING_THRESHOLD:
        span_txt = (
            f" between {span[0].strftime('%m/%Y')} and {span[1].strftime('%m/%Y')}" if span else ""
        )
        lines.append(
            f"- The user's history includes {engagement_count} independent engagements "
            f"(contract/part-time/project/volunteer work){span_txt}. Do not list each one as a "
            "separate experience entry: consolidate them into a single grouped entry (e.g., "
            "position 'Contract Software Engineer', company 'Various Clients') spanning their "
            "combined date range, with bullets naming the engagements most relevant to the job "
            "description. Keep full-time jobs as their own separate entries."
        )

    languages = extract_languages(records)
    if languages:
        rendered = "; ".join(f"{name} — {prof}" if prof else name for name, prof in languages)
        lines.append(
            f"- Languages the user speaks: {rendered}. Include exactly these in the resume's 'languages' "
            "field, writing the language names and proficiency levels in the same language as the rest of "
            "the resume (keep CEFR codes like (C2) unchanged). Never add languages or upgrade proficiency levels."
        )
    else:
        lines.append(
            "- No spoken-language data is stored for this user. Leave the 'languages' field empty; "
            "do not guess."
        )

    return "\n".join(lines)
