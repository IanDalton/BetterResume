import chromadb
from langchain.tools import BaseTool
from pydantic import Field, PrivateAttr



from typing import Any


class ChromaDBTool(BaseTool):
    """ChromaDBTool is a tool that interfaces with a ChromaDB database to retrieve and manage information. 
    It initializes a connection to a specified collection and provides methods to add documents and query the database.
    Attributes:
        name (str): The name of the tool, set to "ChromaDBTool".
        description (str): A brief description of the tool's purpose and functionality.
        collection_name (str): The name of the ChromaDB collection to interact with. Defaults to "default_collection".
        persist_directory (str): The directory where the ChromaDB data is persisted. Defaults to "./chroma_db".
    Private Attributes:
        _client (Any): The ChromaDB client instance used to interact with the database.
        _collection (Any): The specific collection within the ChromaDB database.
    Methods:
        __init__(persist_directory: str):
            Initializes the ChromaDBTool instance, setting up the client and collection.
        add_document(document: str, id: str) -> str:
            Adds a single document to the ChromaDB collection.
            Args:
                document (str): The document content to add.
                id (str): The unique identifier for the document.
            Returns:
                str: A success message or an error message if the operation fails.
        add_documents(documents: list, ids: list) -> str:
            Adds multiple documents to the ChromaDB collection.
            Args:
                documents (list): A list of document contents to add.
                ids (list): A list of unique identifiers for the documents.
            Returns:
                str: A success message or an error message if the operation fails.
        _run(query: str, **kwargs) -> list:
            Executes a synchronous query against the ChromaDB collection.
            Args:
                query (str): The text query to execute.
                **kwargs: Additional keyword arguments.
            Returns:
                list: A list of tuples containing document content and their respective distances, or an error message.
        _arun(query: str, **kwargs) -> list:
            Executes an asynchronous query against the ChromaDB collection.
            Args:
                query (str): The text query to execute.
                **kwargs: Additional keyword arguments.
            Returns:
                list: A list of tuples containing document content and their respective distances, or an error message.
    """


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

    def __init__(self, persist_directory: str, collection_name: str | None = None):
        """Create a ChromaDBTool.

        Args:
            persist_directory: Directory for Chroma persistence.
            collection_name: Optional override for collection name (enables multi-user isolation).
        """
        super().__init__()
        if collection_name:
            self.collection_name = collection_name  # override default
        # Use a per-path PersistentClient to avoid SharedSystem settings conflicts
        try:
            self._client = chromadb.PersistentClient(path=persist_directory)  # type: ignore[attr-defined]
        except Exception:
            # Fallback for older chromadb versions
            from chromadb.config import Settings  # type: ignore
            self._client = chromadb.Client(Settings(persist_directory=persist_directory))
        # Ensure collection exists
        try:
            self._collection = self._client.get_or_create_collection(name=self.collection_name)
        except Exception:
            # Fallback to get/create if API differs
            try:
                self._collection = self._client.get_collection(name=self.collection_name)
            except Exception:
                self._collection = self._client.create_collection(name=self.collection_name)

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