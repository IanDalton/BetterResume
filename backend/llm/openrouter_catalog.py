"""OpenRouter model catalog.

Fetches https://openrouter.ai/api/v1/models and normalizes it for the admin
model picker. Cached in-process for an hour: the feed changes slowly and the
picker is admin-only.
"""

import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("betterresume.openrouter_catalog")

MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL_SECONDS = 3600.0
REQUEST_TIMEOUT_SECONDS = 15.0

_CACHE: Dict[str, Any] = {"value": None, "at": 0.0}


class CatalogUnavailable(RuntimeError):
    """The OpenRouter model feed could not be fetched."""


@dataclass(frozen=True)
class CatalogModel:
    id: str
    model_string: str
    name: str
    context_length: Optional[int]
    prompt_price: Optional[float]        # USD per million prompt tokens
    completion_price: Optional[float]    # USD per million completion tokens
    supports_tools: bool
    supports_structured_outputs: bool

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _price_per_mtok(raw: Any) -> Optional[float]:
    """OpenRouter quotes prices per token as strings; report per million tokens."""
    try:
        return float(raw) * 1_000_000
    except (TypeError, ValueError):
        return None


def _parse_entry(entry: Dict[str, Any]) -> Optional[CatalogModel]:
    model_id = entry.get("id")
    if not model_id:
        return None
    params = entry.get("supported_parameters") or []
    pricing = entry.get("pricing") or {}
    try:
        context_length = int(entry["context_length"]) if entry.get("context_length") else None
    except (TypeError, ValueError):
        context_length = None
    return CatalogModel(
        id=model_id,
        model_string=f"openrouter:{model_id}",
        name=entry.get("name") or model_id,
        context_length=context_length,
        prompt_price=_price_per_mtok(pricing.get("prompt")),
        completion_price=_price_per_mtok(pricing.get("completion")),
        supports_tools="tools" in params,
        supports_structured_outputs="structured_outputs" in params,
    )


async def fetch_models(force_refresh: bool = False) -> List[CatalogModel]:
    """Return the normalized catalog, using the cached copy when fresh."""
    now = time.monotonic()
    cached = _CACHE["value"]
    if not force_refresh and cached is not None and (now - _CACHE["at"]) < CACHE_TTL_SECONDS:
        return cached

    headers = {}
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(MODELS_URL, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Expected dict payload, got {type(payload).__name__}")
        data = payload.get("data") or []
    except Exception as exc:
        logger.warning("OpenRouter model feed unavailable: %s", exc)
        raise CatalogUnavailable(str(exc)) from exc

    models = [m for m in (_parse_entry(e) for e in data) if m is not None]
    models.sort(key=lambda m: m.id)
    _CACHE["value"] = models
    _CACHE["at"] = now
    logger.info("Fetched %d models from OpenRouter", len(models))
    return models


def invalidate_cache() -> None:
    _CACHE["value"] = None
    _CACHE["at"] = 0.0
