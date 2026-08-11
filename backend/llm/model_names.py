"""Provider-prefixed model strings: normalization and validation.

Lives apart from `llm.agent` so `llm.model_config` (which `agent` imports) can
validate what it stores without a circular import.

Model strings are `provider:model` as pydantic-ai understands them. Prefixes we
used historically are mapped onto current ones -- notably `google-gla`, which
pydantic-ai removed in favour of `google` for the Gemini API. Anything stored in
`app_settings` or read from the environment goes through here, so a stale prefix
in a database row or a deployment's `.env` keeps working instead of failing at
request time with `ValueError: Unknown provider`.
"""

from typing import Optional

from pydantic_ai.providers import infer_provider_class

# Legacy/alias provider prefixes → the name pydantic-ai uses today.
_LEGACY_PROVIDER_MAP = {
    "google_genai": "google",   # LangChain-era prefix
    "gemini": "google",
    "google-gla": "google",     # pydantic-ai's old name for the Gemini API
}


def normalize_model_string(model: str) -> str:
    """Map a legacy provider prefix onto the current one.

    Bare Gemini model names (`gemini-2.5-flash`) are assumed to mean the Google
    provider; every other unprefixed name is returned untouched for the caller
    to validate or reject.
    """
    if ":" in model:
        provider, name = model.split(":", 1)
        return f"{_LEGACY_PROVIDER_MAP.get(provider, provider)}:{name}"
    if model.startswith("gemini"):
        return f"google:{model}"
    return model


def validate_model_string(model: Optional[str]) -> str:
    """Normalize `model` and confirm pydantic-ai can resolve its provider.

    Returns the normalized string. Raises `ValueError` when the string has no
    provider prefix or names a provider pydantic-ai does not know -- checked
    against the provider registry rather than a hand-maintained list, so a
    provider rename in a pydantic-ai upgrade surfaces at configuration time
    instead of on the next generation.
    """
    model = (model or "").strip()
    if ":" not in model or model.startswith(":") or model.endswith(":"):
        raise ValueError(
            f"Model {model!r} must be provider-prefixed, e.g. 'openrouter:qwen/qwen3-coder' "
            "or 'google:gemini-2.5-flash-lite'"
        )
    normalized = normalize_model_string(model)
    provider = normalized.split(":", 1)[0]
    try:
        infer_provider_class(provider)
    except ValueError as exc:
        raise ValueError(
            f"Unknown model provider {provider!r} in {model!r}; pydantic-ai does not "
            "recognize it. Use e.g. 'openrouter:', 'google:', 'openai:' or 'anthropic:'."
        ) from exc
    return normalized
