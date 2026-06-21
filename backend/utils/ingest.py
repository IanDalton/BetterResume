import asyncio
import csv
import os
from typing import List


def load_csv_documents(path: str) -> List[str]:
    """Load a CSV and render each row as a "column: value" document string.

    Mirrors the output format of langchain's CSVLoader, which this replaces.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"CSV not found: {path}")
    docs: List[str] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            docs.append("\n".join(f"{key}: {value or ''}" for key, value in row.items()))
    return docs


async def ingest_jobs_csv_async(path: str, store, user_id: str) -> int:
    """Load a jobs CSV and ingest its rows into the provided PGVectorStore for a specific user.

    Args:
        path: CSV file path.
        store: Initialized PGVectorStore instance.
        user_id: User id used to scope the documents.

    Returns:
        Number of rows ingested.
    """
    docs = load_csv_documents(path)
    ids = [f"{user_id}_{i}" for i in range(len(docs))]
    await store.aadd_documents(docs, ids, user_id=user_id)
    return len(docs)


def ingest_jobs_csv(path: str, store, user_id: str) -> int:
    """Synchronous wrapper around ingest_jobs_csv_async for CLI/legacy callers."""
    return asyncio.run(ingest_jobs_csv_async(path, store, user_id))
