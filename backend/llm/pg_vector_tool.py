import os
import logging
from typing import Annotated, Any, List, Optional
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedState

import psycopg
from pgvector.psycopg import register_vector
from pgvector import Vector
from langchain_openai.embeddings import OpenAIEmbeddings
from langchain.tools import BaseTool
from pydantic import Field, PrivateAttr
from llm.state import State


class PGVectorTool(BaseTool):
    """PGVectorTool implements a LangChain-compatible tool backed by Postgres + pgvector.

    - Uses OpenAIEmbeddings by default (swap provider if needed)
    - Methods: add_documents, delete_user_documents, _run/_arun for querying
    """

    name: str = "PGVectorTool"
    description: str = "Store and query document embeddings in Postgres (pgvector)."

    table_name: str = Field(default="resume_vectors")
    dim: int = Field(default=1536)
    db_url: str = Field(default="")
    user_id: Optional[str] = Field(default=None)

    _conn: Any = PrivateAttr()
    _emb: OpenAIEmbeddings = PrivateAttr()

    def __init__(self, db_url: Optional[str] = "", table_name: Optional[str] = "resume_vectors", dim: Optional[int] = 768, user_id: Optional[str] = None):
        super().__init__()
        self._logger = logging.getLogger("betterresume.pgvector")
        self.db_url =  os.getenv("DATABASE_URL",db_url)
        if self.db_url and self.db_url.startswith("postgresql+asyncpg://"):
            self.db_url = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
        if table_name:
            self.table_name = table_name
        if dim:
            self.dim = dim
        if user_id:
            self.user_id = user_id


        # Connect & register vector adapter
        self._conn = psycopg.connect(self.db_url, autocommit=True)
        register_vector(self._conn)

        # Ensure table exists
        with self._conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    content TEXT,
                    embedding vector({self.dim})
                );
                """
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_embedding ON {self.table_name} USING ivfflat (embedding) WITH (lists = 100);"
            )

        # Embedding provider
        self._emb = OpenAIEmbeddings(
            base_url=os.getenv("EMBEDDING_SERVICE_URL", "http://nomic-embed:80/v1"),
            api_key="asdsad",
            model="nomic-ai/nomic-embed-text-v1.5",
            
        )
        

    def add_documents(self, documents: List[str], ids: List[str], user_id: str):
        """Compute embeddings and upsert to Postgres for a user."""
        try:
            embs = self._emb.embed_documents(documents)
            with self._conn.cursor() as cur:
                for id_, doc, emb in zip(ids, documents, embs):
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name} (id, user_id, content, embedding)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding;
                        """,
                        (id_, user_id, doc, Vector(emb)),
                    )
            self._logger.info("Added %d documents user=%s", len(documents), user_id)
            return "Documents added successfully."
        except Exception as e:
            self._logger.exception("Error adding documents: %s", e)
            return f"Error adding documents: {e}"

    def delete_user_documents(self, user_id: str):
        try:
            with self._conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self.table_name} WHERE user_id = %s", (user_id,))
            return "Deleted"
        except Exception as e:
            self._logger.exception("Error deleting user documents: %s", e)
            return f"Error deleting user documents: {e}"

    def _run(
        self, 
        query: str,
        state: Annotated[State, InjectedState],
        n_results: int = 2,
        **kwargs
    ):
        """Query signature: _run(query: str, n_results: int = 2)
        The user_id is extracted from the tool's runtime config."""
        user_id = state.get("user_id")

        
        if user_id is None:
            raise ValueError("user_id is required for pgvector queries")
        try:
            q_emb = self._emb.embed_query(query)
            with self._conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT content, id, embedding <-> %s AS distance
                    FROM {self.table_name}
                    WHERE user_id = %s
                    ORDER BY distance
                    LIMIT %s;
                    """,
                    (Vector(q_emb), user_id, n_results),
                )
                rows = cur.fetchall()
            return list(zip([r[0] for r in rows], [r[2] for r in rows]))
        except Exception as e:
            self._logger.exception("Error querying: %s", e)
            return f"Error querying: {e}"

    async def _arun(self, query: str,state:Annotated[State, InjectedState], n_results: int = 2, **kwargs):
        return self._run(query, n_results=n_results, state=state, **kwargs)