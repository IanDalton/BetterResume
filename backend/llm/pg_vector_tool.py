import os
import logging
from typing import Any, List, Optional

import psycopg
from pgvector.psycopg import register_vector
from pgvector import Vector
from langchain.embeddings import OpenAIEmbeddings
from langchain.tools import BaseTool
from pydantic import Field, PrivateAttr


class PGVectorTool(BaseTool):
    """PGVectorTool implements a LangChain-compatible tool backed by Postgres + pgvector.

    - Uses OpenAIEmbeddings by default (swap provider if needed)
    - Methods: add_documents, delete_user_documents, _run/_arun for querying
    """

    name: str = "PGVectorTool"
    description: str = "Store and query document embeddings in Postgres (pgvector)."

    table_name: str = Field(default="resume_vectors")
    dim: int = Field(default=1536)

    _conn: Any = PrivateAttr()
    _emb: Any = PrivateAttr()

    def __init__(self, db_url: Optional[str] = None, table_name: Optional[str] = None, dim: Optional[int] = None, user_id: Optional[str] = None):
        super().__init__()
        self._logger = logging.getLogger("betterresume.pgvector")
        self.db_url = db_url or os.getenv("DATABASE_URL")
        if table_name:
            self.table_name = table_name
        if dim:
            self.dim = dim
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
        self._emb = OpenAIEmbeddings()

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

    def _run(self, query: str, **kwargs):
        """Query signature: _run(query: str, user_id: str = ..., n_results: int = 2)"""
        user_id = kwargs.get("user_id")
        n_results = int(kwargs.get("n_results", 2))
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

    async def _arun(self, query: str, **kwargs):
        return self._run(query, **kwargs)