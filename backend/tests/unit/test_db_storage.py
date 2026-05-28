import warnings
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_init_async_db_pool_no_deprecation_warning():
    """init_async_db_pool must pass open=False and call pool.open() — not open in the constructor."""
    mock_pool = AsyncMock()
    mock_pool.open = AsyncMock()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with patch("utils.db_storage.AsyncConnectionPool") as MockPool:
            MockPool.return_value = mock_pool
            import utils.db_storage as db_storage
            db_storage._async_pool = None
            await db_storage.init_async_db_pool("postgresql://fake:fake@localhost:5432/fake")
            db_storage._async_pool = None

        deprecation_warnings = [
            w for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "AsyncConnectionPool" in str(w.message)
            and "deprecated" in str(w.message)
        ]
        assert not deprecation_warnings, f"Unexpected deprecation warnings: {deprecation_warnings}"

    call_kwargs = MockPool.call_args.kwargs
    assert call_kwargs.get("open") is False, "open=False must be passed to AsyncConnectionPool"
    mock_pool.open.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_async_db_pool_skips_when_no_url():
    """init_async_db_pool does nothing (no error) when DATABASE_URL is absent."""
    import utils.db_storage as db_storage
    db_storage._async_pool = None
    await db_storage.init_async_db_pool(None)
    assert db_storage._async_pool is None


@pytest.mark.asyncio
async def test_init_async_db_pool_skips_when_already_initialized():
    """init_async_db_pool is idempotent — second call does not re-create the pool."""
    sentinel = object()
    import utils.db_storage as db_storage
    original = db_storage._async_pool
    db_storage._async_pool = sentinel  # type: ignore[assignment]
    try:
        await db_storage.init_async_db_pool("postgresql://fake:fake@localhost:5432/fake")
        assert db_storage._async_pool is sentinel
    finally:
        db_storage._async_pool = original
