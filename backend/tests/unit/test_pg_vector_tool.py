from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIConnectionError


@pytest.fixture
def pg_vector_tool(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setenv("EMBEDDING_SERVICE_URL", "http://nomic-embed:80/v1")
    from llm.pg_vector_tool import PGVectorTool
    return PGVectorTool(user_id="test_user")


@pytest.mark.asyncio
async def test_aadd_documents_returns_error_string_on_connection_error(pg_vector_tool):
    """aadd_documents must not raise when embedding service is unreachable."""
    mock_emb = MagicMock()
    mock_emb.aembed_documents = AsyncMock(
        side_effect=APIConnectionError(request=MagicMock())
    )
    object.__setattr__(pg_vector_tool, "_emb", mock_emb)

    mock_pool = MagicMock()
    with patch("llm.pg_vector_tool.get_async_pool", return_value=mock_pool):
        result = await pg_vector_tool.aadd_documents(["doc1"], ["id1"], "test_user")

    assert isinstance(result, str)
    assert "Error" in result


@pytest.mark.asyncio
async def test_arun_returns_error_string_on_connection_error(pg_vector_tool):
    """_arun must not raise when embedding service is unreachable."""
    mock_emb = MagicMock()
    mock_emb.aembed_query = AsyncMock(
        side_effect=APIConnectionError(request=MagicMock())
    )
    object.__setattr__(pg_vector_tool, "_emb", mock_emb)

    mock_pool = MagicMock()
    state = {"user_id": "test_user"}
    with patch("llm.pg_vector_tool.get_async_pool", return_value=mock_pool):
        result = await pg_vector_tool._arun("find my experience", state=state)

    assert isinstance(result, str)
    assert "Error" in result


@pytest.mark.asyncio
async def test_aadd_documents_raises_when_pool_missing(pg_vector_tool):
    """aadd_documents must raise RuntimeError when the DB pool is not initialized."""
    with patch("llm.pg_vector_tool.get_async_pool", return_value=None):
        with pytest.raises(RuntimeError, match="pool not initialized"):
            await pg_vector_tool.aadd_documents(["doc1"], ["id1"], "test_user")


@pytest.mark.asyncio
async def test_arun_raises_when_user_id_missing(pg_vector_tool):
    """_arun must raise ValueError when user_id is absent from state."""
    mock_pool = MagicMock()
    with patch("llm.pg_vector_tool.get_async_pool", return_value=mock_pool):
        with pytest.raises(ValueError, match="user_id"):
            await pg_vector_tool._arun("query", state={})
