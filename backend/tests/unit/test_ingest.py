from unittest.mock import AsyncMock, MagicMock

import pytest


def test_ingest_jobs_csv_returns_row_count(tmp_path):
    """ingest_jobs_csv must return the number of CSV rows ingested."""
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text("type,company,description\njob,Acme,Did stuff\ncontract,Beta,Built things\n")

    mock_tool = MagicMock()
    mock_tool.aadd_documents = AsyncMock(return_value="Documents added successfully.")

    from utils.ingest import ingest_jobs_csv
    count = ingest_jobs_csv(str(csv_path), mock_tool, "user_1")
    assert count == 2


def test_ingest_jobs_csv_calls_aadd_documents(tmp_path):
    """ingest_jobs_csv must delegate to tool.aadd_documents with correct user_id."""
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text("type,company,description\njob,Acme,Did stuff\n")

    mock_tool = MagicMock()
    mock_tool.aadd_documents = AsyncMock(return_value="Documents added successfully.")

    from utils.ingest import ingest_jobs_csv
    ingest_jobs_csv(str(csv_path), mock_tool, "user_abc")

    mock_tool.aadd_documents.assert_awaited_once()
    call_args = mock_tool.aadd_documents.await_args
    assert "user_abc" in str(call_args)


def test_ingest_jobs_csv_raises_on_missing_file():
    """ingest_jobs_csv must raise FileNotFoundError for non-existent CSV."""
    mock_tool = MagicMock()
    from utils.ingest import ingest_jobs_csv
    with pytest.raises(FileNotFoundError):
        ingest_jobs_csv("/nonexistent/path/jobs.csv", mock_tool, "user_1")
