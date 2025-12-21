import os
from langchain_community.document_loaders.csv_loader import CSVLoader
from llm.pg_vector_tool import PGVectorTool

def ingest_jobs_csv(path: str, tool: PGVectorTool, user_id: str) -> int:
    """Load a jobs CSV and ingest its rows into the provided PGVectorTool for a specific user.

    Args:
        path: CSV file path.
        tool: Initialized PGVectorTool instance.
        user_id: User id used to scope the documents.

    Returns:
        Number of rows ingested.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"CSV not found: {path}")
    data = CSVLoader(file_path=path).load()
    ids = [f"{user_id}_{i}" for i in range(len(data))]
    tool.add_documents([d.page_content for d in data], ids, user_id=user_id)
    return len(data)
