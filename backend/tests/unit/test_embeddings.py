"""Tests for the httpx-based EmbeddingClient (replaces langchain_openai embeddings)."""

import json

import httpx
import pytest

from llm.embeddings import EmbeddingClient


def _make_transport(recorder: list):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        recorder.append(payload)
        inputs = payload["input"]
        data = [
            # Return reversed order to verify the client re-sorts by index
            {"index": i, "embedding": [float(i), float(len(text))]}
            for i, text in enumerate(inputs)
        ][::-1]
        return httpx.Response(200, json={"data": data})

    return httpx.MockTransport(handler)


async def test_embed_documents_preserves_order():
    requests = []
    client = EmbeddingClient(base_url="http://test/v1", transport=_make_transport(requests))

    embs = await client.aembed_documents(["a", "bb", "ccc"])

    assert len(embs) == 3
    # index i encoded in first dimension — order must match input order
    assert [e[0] for e in embs] == [0.0, 1.0, 2.0]
    assert [e[1] for e in embs] == [1.0, 2.0, 3.0]


async def test_embed_documents_chunks_requests():
    requests = []
    client = EmbeddingClient(base_url="http://test/v1", chunk_size=2, transport=_make_transport(requests))

    await client.aembed_documents(["a", "b", "c", "d", "e"])

    assert len(requests) == 3
    assert [len(r["input"]) for r in requests] == [2, 2, 1]


async def test_embed_query_returns_single_vector():
    requests = []
    client = EmbeddingClient(base_url="http://test/v1", transport=_make_transport(requests))

    emb = await client.aembed_query("hello")

    assert emb == [0.0, 5.0]


async def test_embed_documents_raises_on_http_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(500, json={"error": "boom"}))
    client = EmbeddingClient(base_url="http://test/v1", transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        await client.aembed_documents(["a"])


def test_base_url_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_SERVICE_URL", "http://from-env:80/v1/")
    client = EmbeddingClient()
    assert client.base_url == "http://from-env:80/v1"
