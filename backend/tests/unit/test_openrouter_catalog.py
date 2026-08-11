"""Tests for the OpenRouter model catalog (network fully mocked)."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from llm import openrouter_catalog as catalog

SAMPLE_FEED = {
    "data": [
        {
            "id": "qwen/qwen3-coder-30b-a3b-instruct",
            "name": "Qwen3 Coder 30B",
            "context_length": 262144,
            "pricing": {"prompt": "0.0000002", "completion": "0.0000008"},
            "supported_parameters": ["temperature", "max_tokens"],
        },
        {
            "id": "google/gemini-2.5-flash-lite",
            "name": "Gemini 2.5 Flash Lite",
            "context_length": 1048576,
            "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
            "supported_parameters": ["tools", "tool_choice", "structured_outputs"],
        },
    ]
}


@pytest.fixture(autouse=True)
def _clear_cache():
    catalog.invalidate_cache()
    yield
    catalog.invalidate_cache()


def _mock_get(payload=SAMPLE_FEED, status=200):
    response = httpx.Response(status, json=payload, request=httpx.Request("GET", catalog.MODELS_URL))
    return patch.object(httpx.AsyncClient, "get", AsyncMock(return_value=response))


async def test_parses_models_and_capabilities():
    with _mock_get():
        models = await catalog.fetch_models(force_refresh=True)

    by_id = {m.id: m for m in models}
    assert by_id["qwen/qwen3-coder-30b-a3b-instruct"].supports_tools is False
    assert by_id["google/gemini-2.5-flash-lite"].supports_tools is True
    assert by_id["google/gemini-2.5-flash-lite"].supports_structured_outputs is True


async def test_model_string_is_provider_prefixed():
    with _mock_get():
        models = await catalog.fetch_models(force_refresh=True)
    assert models[0].model_string == "openrouter:qwen/qwen3-coder-30b-a3b-instruct"


async def test_prices_normalized_to_per_million_tokens():
    with _mock_get():
        models = await catalog.fetch_models(force_refresh=True)
    qwen = next(m for m in models if m.id.startswith("qwen/"))
    assert qwen.prompt_price == pytest.approx(0.2)
    assert qwen.completion_price == pytest.approx(0.8)


async def test_second_call_is_served_from_cache():
    with _mock_get() as mocked:
        await catalog.fetch_models(force_refresh=True)
        await catalog.fetch_models()
    assert mocked.call_count == 1


async def test_cache_expires():
    with _mock_get() as mocked:
        await catalog.fetch_models(force_refresh=True)
        catalog._CACHE["at"] -= catalog.CACHE_TTL_SECONDS + 1
        await catalog.fetch_models()
    assert mocked.call_count == 2


async def test_http_error_raises_catalog_unavailable():
    with _mock_get(payload={"error": "nope"}, status=500):
        with pytest.raises(catalog.CatalogUnavailable):
            await catalog.fetch_models(force_refresh=True)


async def test_transport_error_raises_catalog_unavailable():
    with patch.object(httpx.AsyncClient, "get", AsyncMock(side_effect=httpx.ConnectError("boom"))):
        with pytest.raises(catalog.CatalogUnavailable):
            await catalog.fetch_models(force_refresh=True)


async def test_malformed_entries_are_skipped():
    with _mock_get(payload={"data": [{"no_id": True}, SAMPLE_FEED["data"][1]]}):
        models = await catalog.fetch_models(force_refresh=True)
    assert len(models) == 1


async def test_as_dict_shape():
    with _mock_get():
        models = await catalog.fetch_models(force_refresh=True)
    d = models[0].as_dict()
    assert set(d) == {
        "id", "model_string", "name", "context_length",
        "prompt_price", "completion_price", "supports_tools", "supports_structured_outputs",
    }
