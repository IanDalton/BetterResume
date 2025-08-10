import os
from langchain_community.document_loaders.csv_loader import CSVLoader
from llm.chroma_db_tool import ChromaDBTool

def ingest_jobs_csv(path: str, tool: ChromaDBTool) -> int:
    """Load a jobs CSV and ingest its rows into the provided ChromaDBTool.

    Args:
        path: CSV file path.
        tool: Initialized ChromaDBTool instance.

    Returns:
        Number of rows ingested.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"CSV not found: {path}")
    data = CSVLoader(file_path=path).load()
    try:
        current = tool._collection.count()
    except Exception:
        current = 0
    tool.add_documents(
        [d.page_content for d in data],
        [str(current + i) for i, _ in enumerate(data)],
    )
    return len(data)
