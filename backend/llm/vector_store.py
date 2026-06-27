import asyncio
import logging
import os
from typing import List, Optional, Tuple

from pgvector import Vector

from llm.embeddings import EmbeddingClient
from utils.db_storage import get_async_pool


class PGVectorStore:
    """Postgres + pgvector backed semantic store for user experience documents.

    Plain class (no framework base) — the pydantic-ai agent exposes this through
    its `search_experience` tool.
    """

    def __init__(
        self,
        db_url: Optional[str] = "",
        table_name: str = "resume_vectors",
        dim: int = 768,
        user_id: Optional[str] = None,
        embeddings: Optional[EmbeddingClient] = None,
    ):
        self._logger = logging.getLogger("betterresume.pgvector")
        self.db_url = os.getenv("DATABASE_URL", db_url)
        if self.db_url and self.db_url.startswith("postgresql+asyncpg://"):
            self.db_url = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
        self.table_name = table_name
        self.dim = dim
        self.user_id = user_id
        self._emb = embeddings or EmbeddingClient(chunk_size=8)

    def _run_sync(self, coro):
        """Run an async coroutine from sync context; raise if already in running loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        coro.close()
        raise RuntimeError("Cannot call sync PGVectorStore method while an event loop is running; use the async variant instead.")

    async def aadd_documents(self, documents: List[str], ids: List[str], user_id: str):
        """Compute embeddings and upsert to Postgres for a user (async)."""
        pool = get_async_pool()
        if not pool:
            raise RuntimeError("Database pool not initialized")

        # Truncate documents to avoid token limit errors (512 tokens max for the embedding model)
        truncated_docs = [doc[:500] for doc in documents]
        try:
            embs = await self._emb.aembed_documents(truncated_docs)
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    for id_, doc, emb in zip(ids, documents, embs):
                        await cur.execute(
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

    def add_documents(self, documents: List[str], ids: List[str], user_id: str):
        return self._run_sync(self.aadd_documents(documents, ids, user_id))

    async def adelete_user_documents(self, user_id: str):
        pool = get_async_pool()
        if not pool:
            raise RuntimeError("Database pool not initialized")
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(f"DELETE FROM {self.table_name} WHERE user_id = %s", (user_id,))
            return "Deleted"
        except Exception as e:
            self._logger.exception("Error deleting user documents: %s", e)
            return f"Error deleting user documents: {e}"

    def delete_user_documents(self, user_id: str):
        return self._run_sync(self.adelete_user_documents(user_id))

    async def acount_user_documents(self, user_id: str) -> int:
        pool = get_async_pool()
        if not pool:
            raise RuntimeError("Database pool not initialized")
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT COUNT(*) FROM {self.table_name} WHERE user_id = %s", (user_id,))
                row = await cur.fetchone()
                return row[0] if row else 0

    async def aquery(self, query: str, user_id: Optional[str], n_results: int = 10) -> List[Tuple[str, float]]:
        """Return (content, distance) tuples for the closest documents of a user."""
        pool = get_async_pool()
        if not pool:
            raise RuntimeError("Database pool not initialized")

        if user_id is None:
            raise ValueError("user_id is required for pgvector queries")
        try:
            q_emb = await self._emb.aembed_query(query)
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        f"""
                        SELECT content, id, embedding <-> %s AS distance
                        FROM {self.table_name}
                        WHERE user_id = %s
                        ORDER BY distance
                        LIMIT %s;
                        """,
                        (Vector(q_emb), user_id, n_results),
                    )
                    rows = await cur.fetchall()
            return list(zip([r[0] for r in rows], [r[2] for r in rows]))
        except Exception as e:
            self._logger.exception("Error querying: %s", e)
            return f"Error querying: {e}"
