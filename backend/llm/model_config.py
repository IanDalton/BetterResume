"""Runtime, per-task model configuration.

The model used for each LLM task is stored in the `app_settings` table so the
admin dashboard can change it without a redeploy. Environment variables remain
the bootstrap default: they seed the value when no row exists, and act as the
last resort if the database is unreachable. They never override a stored value.

Reads are cached in-process for CACHE_TTL_SECONDS, so a generation request costs
no extra database round-trip in the common case and every worker converges on a
new setting within the TTL.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from utils.db_storage import DBStorage

logger = logging.getLogger("betterresume.model_config")

TASKS = ("generation", "translation", "import")
SETTING_KEYS = {task: f"model.{task}" for task in TASKS}
CACHE_TTL_SECONDS = 30.0

# Env var consulted per task, falling back to DEFAULT_MODEL.
_ENV_VARS = {
    "generation": "DEFAULT_MODEL",
    "translation": "TRANSLATION_MODEL",
    "import": "IMPORT_MODEL",
}
_ENV_FALLBACK_VARS = {task: f"{task.upper()}_FALLBACK_MODEL" for task in TASKS}
_DEFAULT_MODEL_FALLBACK = "openrouter:wafer/fp4"

_CACHE: Dict[str, Any] = {"value": None, "at": 0.0}


@dataclass(frozen=True)
class TaskModels:
    primary: str
    fallback: Optional[str]


@dataclass(frozen=True)
class ModelConfig:
    generation: TaskModels
    translation: TaskModels
    import_: TaskModels

    def for_task(self, task: str) -> TaskModels:
        if task not in TASKS:
            raise ValueError(f"Unknown task {task!r}; expected one of {TASKS}")
        return getattr(self, "import_" if task == "import" else task)


def _env_models(task: str) -> TaskModels:
    default = os.environ.get("DEFAULT_MODEL") or _DEFAULT_MODEL_FALLBACK
    primary = os.environ.get(_ENV_VARS[task]) or default
    return TaskModels(primary=primary, fallback=os.environ.get(_ENV_FALLBACK_VARS[task]) or None)


def _load_task(task: str) -> TaskModels:
    env = _env_models(task)
    try:
        stored = DBStorage().get_app_setting(SETTING_KEYS[task])
    except Exception:
        logger.warning("Could not read %s from app_settings; using env defaults", SETTING_KEYS[task], exc_info=True)
        return env
    if not stored or not stored.get("primary"):
        return env
    return TaskModels(primary=stored["primary"], fallback=stored.get("fallback") or None)


def get_model_config(force_refresh: bool = False) -> ModelConfig:
    """Current per-task model configuration (TTL-cached)."""
    now = time.monotonic()
    cached = _CACHE["value"]
    if not force_refresh and cached is not None and (now - _CACHE["at"]) < CACHE_TTL_SECONDS:
        return cached
    config = ModelConfig(
        generation=_load_task("generation"),
        translation=_load_task("translation"),
        import_=_load_task("import"),
    )
    _CACHE["value"] = config
    _CACHE["at"] = now
    return config


def invalidate_cache() -> None:
    _CACHE["value"] = None
    _CACHE["at"] = 0.0


def _validate_model_string(model: str) -> str:
    model = (model or "").strip()
    if ":" not in model or model.startswith(":") or model.endswith(":"):
        raise ValueError(
            f"Model {model!r} must be provider-prefixed, e.g. 'openrouter:qwen/qwen3-coder' "
            "or 'google-gla:gemini-2.5-flash-lite'"
        )
    return model


def set_task_models(task: str, primary: str, fallback: Optional[str], updated_by: Optional[str] = None) -> None:
    """Persist the primary/fallback pair for one task and invalidate the cache."""
    if task not in TASKS:
        raise ValueError(f"Unknown task {task!r}; expected one of {TASKS}")
    value = {
        "primary": _validate_model_string(primary),
        "fallback": _validate_model_string(fallback) if fallback else None,
    }
    DBStorage().set_app_setting(SETTING_KEYS[task], value, updated_by)
    invalidate_cache()
    logger.info("Model for task %s set to %s (fallback=%s) by %s", task, value["primary"], value["fallback"], updated_by)
