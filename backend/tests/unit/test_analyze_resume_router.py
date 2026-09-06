"""`POST /resume/analyze-resume/{user_id}`: validation and the contract that
the client sends back the generated resume and gets ATS + review scores."""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers import resume as resume_router
from llm.resume_analysis import ATSAnalysis, ResumeAnalysis
from utils.db_storage import DBStorage

USER = "user_12345678"


def _client():
    app = FastAPI()
    app.include_router(resume_router.router, prefix="/resume")
    return TestClient(app)


def _analysis():
    return ResumeAnalysis(
        ats=ATSAnalysis(score=72, keyword_coverage=65, matched_keywords=["Python"], missing_keywords=["Go"], issues=[]),
        review=None,
        review_error="judge down",
        model=None,
    )


def test_rejects_invalid_user_id(sample_resume_output):
    resp = _client().post("/resume/analyze-resume/guest", json={
        "job_description": "jd", "resume": sample_resume_output.model_dump(),
    })
    assert resp.status_code == 400


def test_rejects_blank_job_description(sample_resume_output):
    resp = _client().post(f"/resume/analyze-resume/{USER}", json={
        "job_description": "   ", "resume": sample_resume_output.model_dump(),
    })
    assert resp.status_code == 400


def test_rejects_a_payload_that_is_not_a_resume():
    resp = _client().post(f"/resume/analyze-resume/{USER}", json={
        "job_description": "jd", "resume": {"language": "en", "resume_section": {"title": "x"}},
    })
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Invalid resume payload"


def test_returns_the_analysis(sample_resume_output):
    fake = AsyncMock(return_value=_analysis())
    with patch.object(resume_router, "analyze_resume", fake):
        resp = _client().post(f"/resume/analyze-resume/{USER}", json={
            "job_description": "Senior Python engineer",
            "resume": sample_resume_output.model_dump(),
            "language": "es",
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["ats"]["score"] == 72
    assert body["ats"]["missing_keywords"] == ["Go"]
    assert body["review"] is None
    assert body["review_error"] == "judge down"

    args, kwargs = fake.call_args
    assert args[0].resume_section.title == sample_resume_output.resume_section.title
    assert args[1] == "Senior Python engineer"
    assert kwargs["language"] == "es"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_analysis_is_recorded_against_the_latest_generation_model(sample_resume_output):
    from llm.resume_analysis import ReviewAnalysis, ReviewScores
    reviewed = ResumeAnalysis(
        ats=ATSAnalysis(score=72, keyword_coverage=65, matched_keywords=[], missing_keywords=[], issues=[]),
        review=ReviewAnalysis(
            relevance=8, quality=6, coherence=9, summary="ok", strengths=[], recommendations=[], keywords_to_add=[],
            scores=ReviewScores(overall=77, relevance=80, quality=60, coherence=90),
        ),
        model="openrouter:judge",
    )
    with patch.object(resume_router, "analyze_resume", AsyncMock(return_value=reviewed)), \
         patch.object(DBStorage, "get_latest_generation_model", return_value="openrouter:gen") as latest, \
         patch.object(DBStorage, "record_resume_analysis") as record:
        resp = _client().post(f"/resume/analyze-resume/{USER}", json={
            "job_description": "jd", "resume": sample_resume_output.model_dump(),
        })
    assert resp.status_code == 200
    latest.assert_called_once_with(USER)
    kwargs = record.call_args.kwargs
    assert kwargs["source"] == "generated"
    assert kwargs["generation_model"] == "openrouter:gen"
    assert kwargs["review_model"] == "openrouter:judge"
    assert (kwargs["ats_score"], kwargs["review_overall"], kwargs["review_quality"]) == (72, 77, 60)


def test_a_recording_failure_does_not_fail_the_request(sample_resume_output):
    with patch.object(resume_router, "analyze_resume", AsyncMock(return_value=_analysis())), \
         patch.object(DBStorage, "get_latest_generation_model", side_effect=RuntimeError("db down")):
        resp = _client().post(f"/resume/analyze-resume/{USER}", json={
            "job_description": "jd", "resume": sample_resume_output.model_dump(),
        })
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PDF analysis
# ---------------------------------------------------------------------------

def _pdf(content: bytes = b"%PDF-1.4 fake"):
    return {"file": ("cv.pdf", content, "application/pdf")}


def _parsed_result():
    from utils.resume_import import ImportedEntry, ResumeImportResult
    return ResumeImportResult(
        experience=[ImportedEntry(type="job", company="Acme", role="Engineer", start_date="01/03/2021",
                                  end_date="present", description="- Built APIs")],
        skills=["Python"],
        warnings=["Ambiguous end date for Acme"],
    )


def test_pdf_rejects_non_pdf():
    resp = _client().post(f"/resume/analyze-resume-pdf/{USER}", data={"job_description": "jd"},
                          files={"file": ("cv.txt", b"hello", "text/plain")})
    assert resp.status_code == 400


def test_pdf_rejects_blank_job_description():
    resp = _client().post(f"/resume/analyze-resume-pdf/{USER}", data={"job_description": " "}, files=_pdf())
    assert resp.status_code == 400


def test_pdf_maps_unreadable_and_parser_failures():
    from utils.resume_import import ResumePdfEmptyError
    with patch.object(resume_router, "parse_resume_pdf", AsyncMock(side_effect=ResumePdfEmptyError("empty"))):
        assert _client().post(f"/resume/analyze-resume-pdf/{USER}", data={"job_description": "jd"}, files=_pdf()).status_code == 422
    with patch.object(resume_router, "parse_resume_pdf", AsyncMock(side_effect=RuntimeError("llm down"))):
        assert _client().post(f"/resume/analyze-resume-pdf/{USER}", data={"job_description": "jd"}, files=_pdf()).status_code == 502


def test_pdf_without_experience_is_422():
    from utils.resume_import import ResumeImportResult
    with patch.object(resume_router, "parse_resume_pdf", AsyncMock(return_value=ResumeImportResult())):
        resp = _client().post(f"/resume/analyze-resume-pdf/{USER}", data={"job_description": "jd"}, files=_pdf())
    assert resp.status_code == 422
    assert "experience" in resp.json()["detail"]


def test_pdf_returns_analysis_with_parsed_resume_and_records_it_as_imported():
    fake_analyze = AsyncMock(return_value=_analysis())
    with patch.object(resume_router, "parse_resume_pdf", AsyncMock(return_value=_parsed_result())), \
         patch.object(resume_router, "analyze_resume", fake_analyze), \
         patch.object(DBStorage, "get_latest_generation_model") as latest, \
         patch.object(DBStorage, "record_resume_analysis") as record:
        resp = _client().post(f"/resume/analyze-resume-pdf/{USER}",
                              data={"job_description": "Senior Python", "language": "es"}, files=_pdf())

    assert resp.status_code == 200
    body = resp.json()
    assert body["ats"]["score"] == 72
    assert body["resume"]["resume_section"]["experience"][0]["company"] == "Acme"
    assert body["resume"]["resume_section"]["experience"][0]["start_date"] == "03/2021"
    assert body["warnings"] == ["Ambiguous end date for Acme"]

    args, kwargs = fake_analyze.call_args
    assert args[0].resume_section.skills[0].name == "Python"
    assert args[1] == "Senior Python"
    assert kwargs["language"] == "es"
    latest.assert_not_called()
    assert record.call_args.kwargs["source"] == "imported"
    assert record.call_args.kwargs["generation_model"] is None
