"""Tests for utils.generation_context — the authoritative facts injected into the
generation prompt (current date, computed years of experience, spoken languages)."""

from datetime import date

from utils.generation_context import (
    build_generation_context,
    compute_total_experience_months,
    extract_languages,
    format_display_date,
    format_experience_duration,
    parse_stored_date,
    summarize_groupable_engagements,
)

TODAY = date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def test_parse_dd_mm_yyyy():
    assert parse_stored_date("15/03/2024", TODAY) == date(2024, 3, 1)


def test_parse_mm_yyyy():
    assert parse_stored_date("03/2024", TODAY) == date(2024, 3, 1)


def test_parse_year_only():
    assert parse_stored_date("2024", TODAY) == date(2024, 1, 1)


def test_parse_present_tokens():
    for token in ("present", "Present", "current", "now", "Actual"):
        assert parse_stored_date(token, TODAY) == TODAY


def test_parse_garbage_returns_none():
    assert parse_stored_date("soon", TODAY) is None
    assert parse_stored_date("", TODAY) is None
    assert parse_stored_date(None, TODAY) is None
    assert parse_stored_date("99/99/2024", TODAY) is None


def test_format_display_date():
    assert format_display_date("01/12/2025", TODAY) == "12/2025"
    assert format_display_date("03/2024", TODAY) == "03/2024"
    assert format_display_date("2019", TODAY) == "2019"
    assert format_display_date("present", TODAY) == "Present"
    assert format_display_date("", TODAY) == ""
    assert format_display_date(None, TODAY) == ""
    assert format_display_date("unparseable", TODAY) == "unparseable"


# ---------------------------------------------------------------------------
# Years-of-experience computation
# ---------------------------------------------------------------------------

def test_total_experience_single_ongoing_job():
    records = [{"type": "job", "start_date": "01/01/2024", "end_date": "present"}]
    assert compute_total_experience_months(records, TODAY) == 29  # 01/2024 -> 06/2026


def test_total_experience_merges_overlapping_roles():
    records = [
        {"type": "job", "start_date": "01/01/2024", "end_date": "01/01/2025"},
        {"type": "contract", "start_date": "01/06/2024", "end_date": "01/06/2025"},
    ]
    # Merged interval 01/2024 -> 06/2025 = 17 months, not 12 + 12
    assert compute_total_experience_months(records, TODAY) == 17


def test_total_experience_clamps_future_dates():
    records = [
        {"type": "job", "start_date": "01/01/2025", "end_date": "01/08/2027"},
    ]
    # End clamped to today: 01/2025 -> 06/2026 = 17 months
    assert compute_total_experience_months(records, TODAY) == 17


def test_total_experience_ignores_non_work_types():
    records = [
        {"type": "education", "start_date": "01/01/2020", "end_date": "01/01/2024"},
        {"type": "info", "company": "name", "description": "Jane Doe"},
        {"type": "language", "role": "English", "description": "C2"},
    ]
    assert compute_total_experience_months(records, TODAY) == 0


def test_format_experience_duration():
    assert format_experience_duration(29) == "2 years 5 months"
    assert format_experience_duration(12) == "1 year"
    assert format_experience_duration(1) == "1 month"
    assert format_experience_duration(0) == "0 months"


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------

def test_extract_languages_reads_role_and_description():
    records = [
        {"type": "language", "role": "English", "description": "Full professional proficiency (C2)"},
        {"type": "language", "role": "Spanish", "description": "Native"},
        {"type": "job", "role": "Engineer", "description": "Built stuff"},
    ]
    assert extract_languages(records) == [
        ("English", "Full professional proficiency (C2)"),
        ("Spanish", "Native"),
    ]


def test_extract_languages_falls_back_to_company():
    records = [{"type": "language", "company": "German", "description": "B2"}]
    assert extract_languages(records) == [("German", "B2")]


# ---------------------------------------------------------------------------
# Grouping of contract/mixed engagements
# ---------------------------------------------------------------------------

CONTRACTS = [
    {"type": "contract", "company": "Client A", "start_date": "01/01/2021", "end_date": "01/06/2021"},
    {"type": "contract", "company": "Client B", "start_date": "01/03/2021", "end_date": "01/12/2021"},
    {"type": "project", "company": "Side Project", "start_date": "01/01/2022", "end_date": "01/05/2022"},
    {"type": "part-time", "company": "Client C", "start_date": "01/06/2022", "end_date": "present"},
]


def test_summarize_groupable_engagements_counts_and_span():
    count, span = summarize_groupable_engagements(CONTRACTS, TODAY)
    assert count == 4
    assert span == (date(2021, 1, 1), TODAY)  # ongoing part-time runs to today


def test_summarize_ignores_full_time_jobs_and_non_work():
    records = [
        {"type": "job", "start_date": "01/01/2020", "end_date": "present"},
        {"type": "education", "start_date": "01/01/2018", "end_date": "01/01/2022"},
        {"type": "language", "role": "English", "description": "C2"},
    ]
    count, span = summarize_groupable_engagements(records, TODAY)
    assert count == 0
    assert span is None


def test_context_tells_model_to_group_many_engagements():
    records = CONTRACTS + [{"type": "job", "company": "Acme", "start_date": "01/01/2024", "end_date": "present"}]
    ctx = build_generation_context(records, today=TODAY)
    assert "4 independent engagements" in ctx
    assert "between 01/2021 and 06/2026" in ctx
    assert "consolidate them into a single grouped entry" in ctx
    assert "Keep full-time jobs as their own separate entries" in ctx


def test_context_does_not_group_few_engagements():
    records = CONTRACTS[:2]  # below the threshold
    ctx = build_generation_context(records, today=TODAY)
    assert "independent engagements" not in ctx


# ---------------------------------------------------------------------------
# Context block
# ---------------------------------------------------------------------------

def test_context_includes_date_experience_and_languages():
    records = [
        {"type": "job", "start_date": "01/01/2024", "end_date": "present"},
        {"type": "language", "role": "English", "description": "Full professional proficiency (C2)"},
    ]
    ctx = build_generation_context(records, today=TODAY)
    assert "06/2026" in ctx
    assert "2 years 5 months" in ctx
    assert "English — Full professional proficiency (C2)" in ctx


def test_context_without_languages_says_omit():
    records = [{"type": "job", "start_date": "01/01/2024", "end_date": "present"}]
    ctx = build_generation_context(records, today=TODAY)
    assert "No spoken-language data" in ctx


def test_context_without_work_history_omits_experience_claim():
    ctx = build_generation_context([], today=TODAY)
    assert "total professional experience" not in ctx
    assert "06/2026" in ctx
