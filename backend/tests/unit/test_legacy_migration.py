"""Tests for utils.legacy_migration -- the safe, idempotent backfill of legacy
type='info'/'language' job_experiences rows into user_profile/
user_profile_links/user_languages.
"""

from unittest.mock import MagicMock, call

from utils.legacy_migration import (
    backfill_personal_info_and_languages,
    decode_legacy_info_row,
    decode_legacy_language_row,
)


# ---------------------------------------------------------------------------
# decode_legacy_info_row
# ---------------------------------------------------------------------------

def test_decode_info_row_name():
    row = {"company": "name", "description": "Jane Doe"}
    assert decode_legacy_info_row(row) == ("profile_field", ("full_name", "Jane Doe"))


def test_decode_info_row_email_phone_address():
    assert decode_legacy_info_row({"company": "email", "description": "jane@example.com"}) == (
        "profile_field", ("email", "jane@example.com"),
    )
    assert decode_legacy_info_row({"company": "phone", "description": "555-1234"}) == (
        "profile_field", ("phone", "555-1234"),
    )
    assert decode_legacy_info_row({"company": "address", "description": "123 Main St"}) == (
        "profile_field", ("address", "123 Main St"),
    )


def test_decode_info_row_website_known_kind():
    row = {"company": "website", "description": "https://linkedin.com/in/jane\nlinkedin"}
    assert decode_legacy_info_row(row) == (
        "link", {"kind": "linkedin", "label": None, "url": "https://linkedin.com/in/jane"},
    )


def test_decode_info_row_website_custom_label():
    row = {"company": "website", "description": "https://jane.dev\nMy Blog"}
    assert decode_legacy_info_row(row) == (
        "link", {"kind": "other", "label": "My Blog", "url": "https://jane.dev"},
    )


def test_decode_info_row_website_no_label():
    row = {"company": "website", "description": "https://jane.dev"}
    assert decode_legacy_info_row(row) == (
        "link", {"kind": "other", "label": None, "url": "https://jane.dev"},
    )


def test_decode_info_row_website_missing_url_skipped():
    assert decode_legacy_info_row({"company": "website", "description": ""}) is None


def test_decode_info_row_unknown_key_skipped():
    assert decode_legacy_info_row({"company": "mystery", "description": "x"}) is None


def test_decode_info_row_case_insensitive_key():
    row = {"company": "  Name  ", "description": "Jane Doe"}
    assert decode_legacy_info_row(row) == ("profile_field", ("full_name", "Jane Doe"))


# ---------------------------------------------------------------------------
# decode_legacy_language_row
# ---------------------------------------------------------------------------

def test_decode_language_row_reads_role_and_description():
    row = {"role": "English", "description": "Full professional proficiency (C2)"}
    assert decode_legacy_language_row(row) == {"name": "English", "proficiency": "Full professional proficiency (C2)"}


def test_decode_language_row_falls_back_to_company():
    row = {"company": "German", "description": "B2"}
    assert decode_legacy_language_row(row) == {"name": "German", "proficiency": "B2"}


def test_decode_language_row_missing_name_returns_none():
    assert decode_legacy_language_row({"description": "C2"}) is None


# ---------------------------------------------------------------------------
# backfill_personal_info_and_languages orchestration
# ---------------------------------------------------------------------------

def _fake_db(rows):
    """Fake DBStorage: returns `rows` once, then an empty list (single batch)."""
    db = MagicMock()
    db.get_unmigrated_legacy_rows.side_effect = [rows, []]
    return db


def test_backfill_upserts_profile_fields_and_marks_migrated():
    rows = [
        {"id": 1, "user_id": "u1", "type": "info", "company": "name", "description": "Jane Doe", "role": None, "raw": {}},
        {"id": 2, "user_id": "u1", "type": "info", "company": "email", "description": "jane@example.com", "role": None, "raw": {}},
    ]
    db = _fake_db(rows)

    stats = backfill_personal_info_and_languages(db)

    assert stats["profile_fields"] == 2
    assert stats["errors"] == 0
    db.upsert_profile_field_from_legacy.assert_has_calls([
        call("u1", "full_name", "Jane Doe"),
        call("u1", "email", "jane@example.com"),
    ], any_order=True)
    db.mark_job_experience_migrated.assert_has_calls([call(1), call(2)], any_order=True)


def test_backfill_inserts_links_with_source_row_id_for_idempotency():
    rows = [
        {"id": 5, "user_id": "u1", "type": "info", "company": "website",
         "description": "https://linkedin.com/in/jane\nlinkedin", "role": None, "raw": {}},
    ]
    db = _fake_db(rows)

    stats = backfill_personal_info_and_languages(db)

    assert stats["links"] == 1
    db.insert_profile_link_from_legacy.assert_called_once_with(
        "u1", "linkedin", None, "https://linkedin.com/in/jane", 5, 0
    )
    db.mark_job_experience_migrated.assert_called_once_with(5)


def test_backfill_inserts_languages():
    rows = [
        {"id": 9, "user_id": "u1", "type": "language", "company": "", "description": "C2", "role": "English", "raw": {}},
    ]
    db = _fake_db(rows)

    stats = backfill_personal_info_and_languages(db)

    assert stats["languages"] == 1
    db.insert_language_from_legacy.assert_called_once_with("u1", "English", "C2", 9, 0)
    db.mark_job_experience_migrated.assert_called_once_with(9)


def test_backfill_skips_unrecognized_rows_without_error():
    rows = [
        {"id": 1, "user_id": "u1", "type": "info", "company": "mystery", "description": "x", "role": None, "raw": {}},
    ]
    db = _fake_db(rows)

    stats = backfill_personal_info_and_languages(db)

    assert stats["skipped"] == 1
    assert stats["errors"] == 0
    # Still marked migrated -- an unrecognized legacy key isn't worth retrying forever.
    db.mark_job_experience_migrated.assert_called_once_with(1)


def test_backfill_continues_after_a_row_error():
    rows = [
        {"id": 1, "user_id": "u1", "type": "info", "company": "name", "description": "Jane", "role": None, "raw": {}},
        {"id": 2, "user_id": "u1", "type": "info", "company": "email", "description": "jane@example.com", "role": None, "raw": {}},
    ]
    db = _fake_db(rows)
    db.upsert_profile_field_from_legacy.side_effect = [RuntimeError("db blip"), None]

    stats = backfill_personal_info_and_languages(db)

    assert stats["errors"] == 1
    # The failing row (id=1) must NOT be marked migrated -- it'll be retried
    # next run, per the idempotent-insert + mark-after-write invariant.
    assert call(1) not in db.mark_job_experience_migrated.call_args_list
    db.mark_job_experience_migrated.assert_called_once_with(2)


def test_backfill_noop_when_nothing_unmigrated():
    db = MagicMock()
    db.get_unmigrated_legacy_rows.return_value = []

    stats = backfill_personal_info_and_languages(db)

    assert stats == {"profile_fields": 0, "links": 0, "languages": 0, "skipped": 0, "errors": 0}
    db.mark_job_experience_migrated.assert_not_called()
