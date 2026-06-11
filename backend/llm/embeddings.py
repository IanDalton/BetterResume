import logging
import os
from typing import List, Optional

import httpx


class EmbeddingClient:
    """Minimal async client for an OpenAI-compatible embeddings endpoint (HuggingFace TEI).

    Replaces the previous langchain_openai.OpenAIEmbeddings dependency.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: str = "sentence-transformers/all-mpnet-base-v2",
        chunk_size: int = 8,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.base_url = (base_url or os.getenv("EMBEDDING_SERVICE_URL", "http://embedding-service-br:80/v1")).rstrip("/")
        self.model = model
        self.chunk_size = max(1, chunk_size)
        self.timeout = timeout
        self._transport = transport
        self._logger = logging.getLogger("betterresume.embeddings")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, transport=self._transport)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of documents, chunked to respect service limits."""
        embeddings: List[List[float]] = []
        async with self._client() as client:
            for start in range(0, len(texts), self.chunk_size):
                batch = texts[start:start + self.chunk_size]
                resp = await client.post("/embeddings", json={"model": self.model, "input": batch})
                resp.raise_for_status()
                data = resp.json()["data"]
                # OpenAI-compatible APIs return items with an "index" field; keep order stable
                data.sort(key=lambda item: item.get("index", 0))
                embeddings.extend(item["embedding"] for item in data)
        self._logger.debug("Embedded %d documents", len(texts))
        return embeddings

    async def aembed_query(self, text: str) -> List[float]:
        result = await self.aembed_documents([text])
        return result[0]
