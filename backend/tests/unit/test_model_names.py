"""Provider-prefix normalization and validation.

Regression cover for the `google-gla` outage: pydantic-ai dropped that provider
name (the Gemini API is `google:`), so every model string we ship or store must
name a provider pydantic-ai still knows -- otherwise the first request with it
dies with `ValueError: Unknown provider: ...`, far from the config that set it.
"""

from pathlib import Path

import pytest
from pydantic_ai.providers import infer_provider_class

from llm.model_names import normalize_model_string, validate_model_string

ENV_TEMPLATE = Path(__file__).resolve().parents[2] / ".env.template"


def test_legacy_google_gla_prefix_maps_to_google():
    assert normalize_model_string("google-gla:gemini-2.5-flash-lite") == "google:gemini-2.5-flash-lite"


def test_legacy_google_genai_prefix_maps_to_google():
    assert normalize_model_string("google_genai:gemini-2.5-flash-lite") == "google:gemini-2.5-flash-lite"


def test_bare_gemini_name_gets_google_prefix():
    assert normalize_model_string("gemini-2.5-flash") == "google:gemini-2.5-flash"


def test_other_providers_pass_through():
    assert normalize_model_string("openrouter:qwen/qwen3-coder") == "openrouter:qwen/qwen3-coder"
    assert normalize_model_string("openai:gpt-4o-mini") == "openai:gpt-4o-mini"


@pytest.mark.parametrize("legacy", ["google_genai", "gemini", "google", "google-gla"])
def test_every_normalized_prefix_is_a_provider_pydantic_ai_knows(legacy):
    provider = normalize_model_string(f"{legacy}:some-model").split(":", 1)[0]
    infer_provider_class(provider)  # raises ValueError for an unknown provider


def test_validate_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown model provider"):
        validate_model_string("google-gla-typo:gemini-2.5-flash-lite")


def test_validate_rejects_unprefixed_model():
    with pytest.raises(ValueError, match="provider-prefixed"):
        validate_model_string("gpt-4o-mini")


def test_validate_returns_the_normalized_string():
    assert validate_model_string(" google-gla:gemini-2.5-flash-lite ") == "google:gemini-2.5-flash-lite"


def test_shipped_env_template_model_defaults_are_valid():
    """`.env.template` seeds real deployments; a bad model string there breaks
    every run that uses it (a bad *fallback* breaks even healthy primaries,
    since `FallbackModel` resolves both sub-models up front)."""
    for line in ENV_TEMPLATE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not key.endswith("MODEL") or not value.strip():
            continue
        validate_model_string(value.strip())


def test_shipped_model_defaults_are_valid():
    from llm import model_config

    validate_model_string(model_config.SHIPPED_DEFAULT_MODEL)
    validate_model_string(model_config.SHIPPED_JUDGE_MODEL)


def test_shipped_defaults_all_route_through_openrouter():
    """Deployments are meant to need one LLM credential (OPENROUTER_API_KEY);
    a shipped default on another provider silently reintroduces a second one."""
    from llm import model_config

    assert model_config.SHIPPED_DEFAULT_MODEL.startswith("openrouter:")
    assert model_config.SHIPPED_JUDGE_MODEL.startswith("openrouter:")
    for line in ENV_TEMPLATE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.endswith("MODEL") and value.strip():
            assert value.strip().startswith("openrouter:"), key
