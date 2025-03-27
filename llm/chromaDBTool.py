import chromadb
from chromadb.config import Settings
from langchain.tools import BaseTool
from pydantic import Field, PrivateAttr



from typing import Any


class ChromaDBTool(BaseTool):
    name: str = "ChromaDBTool"
    description: str = (
        "A tool that interfaces with a ChromaDB database to retrieve information. "
        "It initializes a connection to a specified collection and runs queries against it."
    )
    collection_name: str = Field(default="default_collection")
    persist_directory: str = Field(default="./chroma_db")

    # Declare private attributes for runtime-only properties.
    _client: Any = PrivateAttr()
    _collection: Any = PrivateAttr()

    def __init__(self):
        super().__init__()
        self._client = chromadb.Client(
            Settings(persist_directory=self.persist_directory))
        try:
            self._collection = self._client.get_collection(
                name=self.collection_name)
        except Exception as e:
            self._collection = self._client.create_collection(
                name=self.collection_name)

    def add_document(self, document: str, id: str):
        """
        Add a document to the ChromaDB collection.
        """
        try:
            self._collection.add(documents=[document], ids=[id])
            return "Document added successfully."
        except Exception as e:
            return f"Error adding document: {e}"

    def add_documents(self, documents: list, ids: list):
        """
        Add multiple documents to the ChromaDB collection.
        """
        try:
            self._collection.add(documents=documents, ids=ids)
            return "Documents added successfully."
        except Exception as e:
            return f"Error adding documents: {e}"

    def _run(self, query: str, **kwargs):
        print("chromadb")
        """
        Synchronous method to query the ChromaDB collection.
        Expects a text query and returns the query results.
        """
        try:
            results = self._collection.query(query_texts=[query], n_results=2)
            return list(zip(results["documents"][0], results["distances"][0]))
        except Exception as e:
            return f"Error querying the database: {e}"

    async def _arun(self, query: str, **kwargs):
        """
        Asynchronous version of the _run method.
        Currently, this calls the synchronous version for simplicity.
        """
        return self._run(query, **kwargs)