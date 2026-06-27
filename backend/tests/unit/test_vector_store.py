"""Tests for PGVectorStore (port of the old PGVectorTool tests, langchain-free)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setenv("EMBEDDING_SERVICE_URL", "http://nomic-embed:80/v1")
    from llm.vector_store import PGVectorStore
    return PGVectorStore(user_id="test_user")


async def test_aadd_documents_returns_error_string_on_embedding_failure(store):
    """aadd_documents must not raise when embedding service is unreachable."""
    mock_emb = MagicMock()
    mock_emb.aembed_documents = AsyncMock(side_effect=ConnectionError("service down"))
    store._emb = mock_emb

    with patch("llm.vector_store.get_async_pool", return_value=MagicMock()):
        result = await store.aadd_documents(["doc1"], ["id1"], "test_user")

    assert isinstance(result, str)
    assert "Error" in result


async def test_aquery_returns_error_string_on_embedding_failure(store):
    """aquery must not raise when embedding service is unreachable."""
    mock_emb = MagicMock()
    mock_emb.aembed_query = AsyncMock(side_effect=ConnectionError("service down"))
    store._emb = mock_emb

    with patch("llm.vector_store.get_async_pool", return_value=MagicMock()):
        result = await store.aquery("find my experience", "test_user")

    assert isinstance(result, str)
    assert "Error" in result


async def test_aadd_documents_raises_when_pool_missing(store):
    with patch("llm.vector_store.get_async_pool", return_value=None):
        with pytest.raises(RuntimeError, match="pool not initialized"):
            await store.aadd_documents(["doc1"], ["id1"], "test_user")


async def test_aquery_raises_when_pool_missing(store):
    with patch("llm.vector_store.get_async_pool", return_value=None):
        with pytest.raises(RuntimeError, match="pool not initialized"):
            await store.aquery("query", "test_user")


async def test_aquery_raises_when_user_id_missing(store):
    with patch("llm.vector_store.get_async_pool", return_value=MagicMock()):
        with pytest.raises(ValueError, match="user_id"):
            await store.aquery("query", None)


async def test_sync_method_rejected_inside_event_loop(store):
    """Sync wrappers must refuse to run while an event loop is active."""
    with pytest.raises(RuntimeError, match="async variant"):
        store.add_documents(["doc"], ["id"], "test_user")


def test_truncates_documents_for_embedding(store, monkeypatch):
    """Documents are truncated to 500 chars before embedding (token limit guard)."""
    captured = {}

    async def fake_embed(docs):
        captured["docs"] = docs
        return [[0.0] * 4 for _ in docs]

    store._emb = MagicMock()
    store._emb.aembed_documents = fake_embed

    # Async pool whose connection fails fast — we only care about the embed call
    pool = MagicMock()
    pool.connection.side_effect = RuntimeError("stop here")

    import asyncio
    with patch("llm.vector_store.get_async_pool", return_value=pool):
        result = asyncio.run(store.aadd_documents(["x" * 1000], ["id1"], "u"))

    assert len(captured["docs"][0]) == 500
    assert "Error" in result  # connection failure surfaced as error string
