"""Tests for api.routers.jobs -- the narrowed work-entry type validation and
the transitional diversion of legacy type='info'/'language' rows to the
dedicated profile/language tables.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import jobs as jobs_router
from api.routers.jobs import _divert_legacy_rows
from utils.db_storage import DBStorage


# ---------------------------------------------------------------------------
# _divert_legacy_rows
# ---------------------------------------------------------------------------

def _storage(profile=None, links=None, languages=None):
    storage = MagicMock()
    storage.get_user_profile.return_value = profile
    storage.list_profile_links.return_value = links or []
    storage.get_user_languages.return_value = languages or []
    return storage


def test_divert_returns_only_work_like_records():
    storage = _storage()
    records = [
        {"type": "info", "company": "name", "description": "Jane Doe"},
        {"type": "job", "company": "Acme", "description": "Built stuff"},
        {"type": "language", "role": "English", "description": "C2"},
    ]

    work_records = _divert_legacy_rows(storage, "u1", records)

    assert work_records == [{"type": "job", "company": "Acme", "description": "Built stuff"}]


def test_divert_merges_info_fields_with_existing_profile():
    storage = _storage(profile={"full_name": "Old Name", "email": "old@example.com", "phone": None, "address": None})
    records = [{"type": "info", "company": "email", "description": "new@example.com"}]

    _divert_legacy_rows(storage, "u1", records)

    storage.upsert_user_profile.assert_called_once_with(
        "u1", full_name="Old Name", email="new@example.com", phone=None, address=None
    )


def test_divert_appends_links_to_existing():
    storage = _storage(links=[{"kind": "github", "label": None, "url": "https://github.com/jane"}])
    records = [{"type": "info", "company": "website", "description": "https://jane.dev\nMy Site"}]

    _divert_legacy_rows(storage, "u1", records)

    storage.replace_profile_links.assert_called_once_with("u1", [
        {"kind": "github", "label": None, "url": "https://github.com/jane"},
        {"kind": "other", "label": "My Site", "url": "https://jane.dev"},
    ])


def test_divert_appends_languages_to_existing():
    storage = _storage(languages=[{"name": "Spanish", "proficiency": "Native"}])
    records = [{"type": "language", "role": "English", "description": "C2"}]

    _divert_legacy_rows(storage, "u1", records)

    storage.replace_user_languages.assert_called_once_with("u1", [
        {"name": "Spanish", "proficiency": "Native"},
        {"name": "English", "proficiency": "C2"},
    ])


def test_divert_no_profile_or_language_calls_when_nothing_to_divert():
    storage = _storage()
    records = [{"type": "job", "company": "Acme", "description": "Built stuff"}]

    _divert_legacy_rows(storage, "u1", records)

    storage.upsert_user_profile.assert_not_called()
    storage.replace_profile_links.assert_not_called()
    storage.replace_user_languages.assert_not_called()


# ---------------------------------------------------------------------------
# Router: type validation + end-to-end diversion
# ---------------------------------------------------------------------------

class FakeStore:
    async def adelete_user_documents(self, user_id):
        return "deleted"

    async def aadd_documents(self, docs, ids, user_id):
        self.added = docs
        return "ok"


def _app():
    app = FastAPI()
    app.include_router(jobs_router.router)
    return app


def test_upload_jobs_rejects_unknown_type():
    app = _app()
    client = TestClient(app)

    with patch.object(DBStorage, "_ensure_user"), \
         patch.object(jobs_router, "get_user_store", return_value=FakeStore()), \
         patch.object(DBStorage, "get_user_profile", return_value=None), \
         patch.object(DBStorage, "list_profile_links", return_value=[]), \
         patch.object(DBStorage, "get_user_languages", return_value=[]):
        resp = client.post("/upload-jobs/testuser123", json={"jobs": [
            {"type": "not-a-real-type", "company": "Acme", "description": "x"},
        ]})

    assert resp.status_code == 400
    assert "not-a-real-type" in resp.json()["detail"]


def test_upload_jobs_diverts_info_row_and_processes_remaining_work_rows():
    app = _app()
    client = TestClient(app)

    with patch.object(DBStorage, "_ensure_user"), \
         patch.object(jobs_router, "get_user_store", return_value=FakeStore()), \
         patch.object(DBStorage, "get_user_profile", return_value=None), \
         patch.object(DBStorage, "list_profile_links", return_value=[]), \
         patch.object(DBStorage, "upsert_user_profile") as upsert_profile, \
         patch.object(DBStorage, "get_user_languages", return_value=[]), \
         patch.object(DBStorage, "save_file") as save_file, \
         patch.object(DBStorage, "replace_job_experiences") as replace_jobs:
        resp = client.post("/upload-jobs/testuser123", json={"jobs": [
            {"type": "info", "company": "name", "description": "Jane Doe"},
            {"type": "job", "company": "Acme", "description": "Built stuff", "role": "Engineer"},
        ]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["rows_ingested"] == 1

    upsert_profile.assert_called_once_with(
        "testuser123", full_name="Jane Doe", email=None, phone=None, address=None
    )
    # Only the work-like row reaches the CSV/job_experiences pipeline.
    saved_records = replace_jobs.call_args.args[1]
    assert len(saved_records) == 1
    assert saved_records[0]["company"] == "Acme"


def test_upload_jobs_all_diverted_yields_empty_result():
    """A payload containing only legacy info/language rows should still
    succeed (0 rows ingested), not error, since there's nothing work-like left."""
    app = _app()
    client = TestClient(app)

    with patch.object(DBStorage, "_ensure_user"), \
         patch.object(jobs_router, "get_user_store", return_value=FakeStore()), \
         patch.object(DBStorage, "get_user_profile", return_value=None), \
         patch.object(DBStorage, "list_profile_links", return_value=[]), \
         patch.object(DBStorage, "upsert_user_profile"), \
         patch.object(DBStorage, "get_user_languages", return_value=[]), \
         patch.object(DBStorage, "save_file"), \
         patch.object(DBStorage, "replace_job_experiences") as replace_jobs:
        resp = client.post("/upload-jobs/testuser123", json={"jobs": [
            {"type": "info", "company": "name", "description": "Jane Doe"},
        ]})

    assert resp.status_code == 200
    assert resp.json()["rows_ingested"] == 0
    replace_jobs.assert_called_once_with("testuser123", [])
