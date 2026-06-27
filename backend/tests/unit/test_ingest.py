"""Tests for CSV document loading and ingestion (langchain CSVLoader replacement)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from utils.ingest import ingest_jobs_csv, load_csv_documents


def test_load_csv_documents_formats_rows(tmp_path):
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text("type,company,description\njob,Acme,Did stuff\ncontract,Beta,Built things\n")

    docs = load_csv_documents(str(csv_path))

    assert docs == [
        "type: job\ncompany: Acme\ndescription: Did stuff",
        "type: contract\ncompany: Beta\ndescription: Built things",
    ]


def test_load_csv_documents_handles_empty_values(tmp_path):
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text("type,company,description\njob,,\n")

    docs = load_csv_documents(str(csv_path))

    assert docs == ["type: job\ncompany: \ndescription: "]


def test_load_csv_documents_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        load_csv_documents("/nonexistent/path/jobs.csv")


def test_ingest_jobs_csv_returns_row_count(tmp_path):
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text("type,company,description\njob,Acme,Did stuff\ncontract,Beta,Built things\n")

    mock_store = MagicMock()
    mock_store.aadd_documents = AsyncMock(return_value="Documents added successfully.")

    count = ingest_jobs_csv(str(csv_path), mock_store, "user_1")
    assert count == 2


def test_ingest_jobs_csv_calls_aadd_documents(tmp_path):
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text("type,company,description\njob,Acme,Did stuff\n")

    mock_store = MagicMock()
    mock_store.aadd_documents = AsyncMock(return_value="Documents added successfully.")

    ingest_jobs_csv(str(csv_path), mock_store, "user_abc")

    mock_store.aadd_documents.assert_awaited_once()
    docs, ids = mock_store.aadd_documents.await_args.args
    assert ids == ["user_abc_0"]
    assert mock_store.aadd_documents.await_args.kwargs["user_id"] == "user_abc"
    assert "company: Acme" in docs[0]


def test_ingest_jobs_csv_raises_on_missing_file():
    mock_store = MagicMock()
    with pytest.raises(FileNotFoundError):
        ingest_jobs_csv("/nonexistent/path/jobs.csv", mock_store, "user_1")
