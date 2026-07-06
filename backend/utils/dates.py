"""Shared date-string normalization helpers.

`normalize_month_year` is a small, testable, defense-in-depth net for
callers whose upstream data is already roughly structured (e.g. an LLM
instructed to emit DD/MM/YYYY directly, per prompts/linkedin_import_prompt.txt).
It intentionally does not attempt to parse localized month names ("Jan",
"enero", etc.) -- that's delegated to the LLM in the LinkedIn-import path,
which handles locale variance far better than a regex table would.

backend/api/routers/jobs.py has its own, separate, numeric-only `_norm_date`
used for the manual entry-upload path; this module is not a refactor of
that -- it exists specifically for the LinkedIn-import pipeline.
"""

import re
from typing import Optional

_DD_MM_YYYY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_MM_YYYY = re.compile(r"^(\d{1,2})/(\d{4})$")
_YYYY_MM = re.compile(r"^(\d{4})[/-](\d{1,2})$")
_PRESENT_TOKENS = {"present", "current", "now"}


def normalize_month_year(value: Optional[str]) -> str:
    """Normalize an already-somewhat-structured date string to DD/MM/YYYY or 'present'.

    Leaves unparseable input as-is (trimmed) rather than raising or dropping
    data -- an imperfect date the user can see and fix beats a silently
    discarded one.
    """
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if s.lower() in _PRESENT_TOKENS:
        return "present"
    m = _DD_MM_YYYY.match(s)
    if m:
        dd, mm, yyyy = m.groups()
        return f"{dd.zfill(2)}/{mm.zfill(2)}/{yyyy}"
    m = _MM_YYYY.match(s)
    if m:
        mm, yyyy = m.groups()
        return f"01/{mm.zfill(2)}/{yyyy}"
    m = _YYYY_MM.match(s)
    if m:
        yyyy, mm = m.groups()
        return f"01/{mm.zfill(2)}/{yyyy}"
    return s
