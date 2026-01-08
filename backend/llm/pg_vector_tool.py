import asyncio
import os
import logging
from typing import Annotated, Any, List, Optional
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import InjectedState

from pgvector import Vector
from langchain_openai.embeddings import OpenAIEmbeddings
from langchain.tools import BaseTool
from pydantic import Field, PrivateAttr
from llm.state import State
from utils.db_storage import get_async_pool


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

    _emb: OpenAIEmbeddings = PrivateAttr()

    def __init__(self, db_url: Optional[str] = "", table_name: Optional[str] = "resume_vectors", dim: Optional[int] = 768, user_id: Optional[str] = None):
        super().__init__()
        self._logger = logging.getLogger("betterresume.pgvector")
        # Ensure we just checking/setting logic but likely ignoring for connection creation as we use global pool
        self.db_url =  os.getenv("DATABASE_URL",db_url)
        if self.db_url and self.db_url.startswith("postgresql+asyncpg://"):
            self.db_url = self.db_url.replace("postgresql+asyncpg://", "postgresql://")
        if table_name:
            self.table_name = table_name
        if dim:
            self.dim = dim
        if user_id:
            self.user_id = user_id

        # Embedding provider
        self._emb = OpenAIEmbeddings(
            base_url=os.getenv("EMBEDDING_SERVICE_URL", "http://nomic-embed:80/v1"),
            api_key="asdsad",
            model="nomic-ai/nomic-embed-text-v1.5",
            chunk_size=8
        )

    def _run_sync(self, coro):
        """Run an async coroutine from sync context; raise if already in running loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError("Cannot call sync PGVectorTool method while an event loop is running; use the async variant instead.")

    async def aadd_documents(self, documents: List[str], ids: List[str], user_id: str):
        """Compute embeddings and upsert to Postgres for a user (async)."""
        pool = get_async_pool()
        if not pool:
            # Fallback or error? better error
            raise RuntimeError("Database pool not initialized")
            
        # Truncate documents to avoid token limit errors (256 tokens max for this model)
        # Using 1000 characters as a safe upper bound approximation
        truncated_docs = [doc[:1000] for doc in documents]
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

    def _run(
        self, 
        query: str,
        state: Annotated[State, InjectedState],
        n_results: int = 2,
        **kwargs
    ):
        return self._run_sync(self._arun(query, state=state, n_results=n_results, **kwargs))

    async def _arun(self, query: str,state:Annotated[State, InjectedState], n_results: int = 2, **kwargs):
        """Async query execution used by LangChain graphs."""
        pool = get_async_pool()
        if not pool:
             raise RuntimeError("Database pool not initialized")
             
        user_id = state.get("user_id")

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