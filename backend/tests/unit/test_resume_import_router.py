"""Tests for POST /resume/import/resume/{user_id} -- validation, error
mapping, and the parse-and-return-for-review contract (nothing is saved
server-side by this endpoint)."""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import resume_import as resume_import_router
from utils.db_storage import DBStorage
from utils.resume_import import ResumeImportResult, ResumePdfEmptyError


def _app():
    app = FastAPI()
    app.include_router(resume_import_router.router)
    return app


def _pdf_file(content: bytes = b"%PDF-1.4 fake content"):
    return {"file": ("resume.pdf", content, "application/pdf")}


def test_rejects_non_pdf_content_type():
    client = TestClient(_app())
    resp = client.post(
        "/import/resume/testuser123",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_rejects_empty_file():
    client = TestClient(_app())
    with patch.object(DBStorage, "save_file"):
        resp = client.post("/import/resume/testuser123", files=_pdf_file(b""))
    assert resp.status_code == 400


def test_rejects_oversized_file():
    client = TestClient(_app())
    oversized = b"0" * (10 * 1024 * 1024 + 1)
    with patch.object(DBStorage, "save_file"):
        resp = client.post("/import/resume/testuser123", files=_pdf_file(oversized))
    assert resp.status_code == 400


def test_returns_422_for_unreadable_pdf():
    client = TestClient(_app())
    with patch.object(DBStorage, "save_file"), \
         patch.object(resume_import_router, "parse_resume_pdf", side_effect=ResumePdfEmptyError("empty")):
        resp = client.post("/import/resume/testuser123", files=_pdf_file())
    assert resp.status_code == 422


def test_returns_502_on_parse_failure():
    client = TestClient(_app())
    with patch.object(DBStorage, "save_file"), \
         patch.object(resume_import_router, "parse_resume_pdf", side_effect=RuntimeError("llm down")):
        resp = client.post("/import/resume/testuser123", files=_pdf_file())
    assert resp.status_code == 502


def test_success_returns_parsed_data_without_saving():
    sample_result = ResumeImportResult(
        profile={"full_name": "Jane Doe", "email": "jane@example.com", "links": [
            {"kind": "github", "label": None, "url": "https://github.com/janedoe"},
        ]},
        experience=[{"type": "job", "company": "Acme Corp", "role": "Engineer", "description": "Built things",
                     "start_date": "01/03/2021", "end_date": "present"}],
        education=[{"type": "education", "company": "UC Berkeley", "role": "B.S. CS", "description": ""}],
        skills=["Python", "FastAPI"],
        languages=[{"name": "English", "proficiency": "Native"}],
        warnings=[],
    )
    client = TestClient(_app())
    with patch.object(DBStorage, "save_file") as save_file, \
         patch.object(resume_import_router, "parse_resume_pdf", return_value=sample_result):
        resp = client.post("/import/resume/testuser123", files=_pdf_file())

    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"]["full_name"] == "Jane Doe"
    assert body["profile"]["links"][0]["kind"] == "github"
    assert body["experience"][0]["company"] == "Acme Corp"
    assert body["education"][0]["company"] == "UC Berkeley"
    assert body["languages"][0]["name"] == "English"
    # The raw PDF is stashed for audit/re-parse, but no profile/job data is committed.
    save_file.assert_called_once()
    assert save_file.call_args.kwargs["file_type"] == "resume_import_pdf_raw"


def test_raw_pdf_save_failure_does_not_fail_the_request():
    sample_result = ResumeImportResult(profile={"full_name": "Jane Doe"})
    client = TestClient(_app())
    with patch.object(DBStorage, "save_file", side_effect=RuntimeError("disk full")), \
         patch.object(resume_import_router, "parse_resume_pdf", return_value=sample_result):
        resp = client.post("/import/resume/testuser123", files=_pdf_file())
    assert resp.status_code == 200
