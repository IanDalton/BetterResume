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

from llm.model_names import validate_model_string
from utils.db_storage import DBStorage

logger = logging.getLogger("betterresume.model_config")

TASKS = ("generation", "translation", "import", "judge")
# Tasks whose model is used through `llm.agent`'s fallback machinery. The judge
# runs a single standalone scoring call in `evals/`, so it has a primary only.
TASKS_WITH_FALLBACK = ("generation", "translation", "import")
SETTING_KEYS = {task: f"model.{task}" for task in TASKS}
CACHE_TTL_SECONDS = 30.0

# Env var consulted per task, falling back to DEFAULT_MODEL.
_ENV_VARS = {
    "generation": "DEFAULT_MODEL",
    "translation": "TRANSLATION_MODEL",
    "import": "IMPORT_MODEL",
    "judge": "JUDGE_MODEL",
}
_ENV_FALLBACK_VARS = {task: f"{task.upper()}_FALLBACK_MODEL" for task in TASKS}
SHIPPED_DEFAULT_MODEL = "openrouter:google/gemini-2.5-flash-lite"
# The judge grades other models' output, so it deliberately does NOT inherit
# DEFAULT_MODEL: scoring a model's resume with that same model is self-grading.
SHIPPED_JUDGE_MODEL = "openrouter:google/gemini-2.5-flash-lite"

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
    judge: TaskModels

    def for_task(self, task: str) -> TaskModels:
        if task not in TASKS:
            raise ValueError(f"Unknown task {task!r}; expected one of {TASKS}")
        return getattr(self, "import_" if task == "import" else task)


def _env_models(task: str) -> TaskModels:
    default = SHIPPED_JUDGE_MODEL if task == "judge" else (
        os.environ.get("DEFAULT_MODEL") or SHIPPED_DEFAULT_MODEL
    )
    primary = os.environ.get(_ENV_VARS[task]) or default
    return TaskModels(primary=primary, fallback=os.environ.get(_ENV_FALLBACK_VARS[task]) or None)


def _load_task(task: str) -> TaskModels:
    env = _env_models(task)
    if not os.environ.get("DATABASE_URL"):
        # Mirrors the early-out in `init_db_pool`: no configured database means
        # nothing to read, so skip the connection attempt entirely rather than
        # let it fail (or hang, on a dropped-packet network) on every call.
        return env
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
        judge=_load_task("judge"),
    )
    _CACHE["value"] = config
    _CACHE["at"] = now
    return config


def invalidate_cache() -> None:
    _CACHE["value"] = None
    _CACHE["at"] = 0.0


def set_task_models(task: str, primary: str, fallback: Optional[str], updated_by: Optional[str] = None) -> None:
    """Persist the primary/fallback pair for one task and invalidate the cache.

    Both strings are normalized and their provider checked here: a row that
    names a provider pydantic-ai cannot resolve would otherwise be accepted
    silently and fail on every subsequent run -- and a bad *fallback* fails even
    when the primary is healthy, because `FallbackModel` resolves both
    sub-models before issuing a request.
    """
    if task not in TASKS:
        raise ValueError(f"Unknown task {task!r}; expected one of {TASKS}")
    if fallback and task not in TASKS_WITH_FALLBACK:
        raise ValueError(f"Task {task!r} does not support a fallback model")
    value = {
        "primary": validate_model_string(primary),
        "fallback": validate_model_string(fallback) if fallback else None,
    }
    DBStorage().set_app_setting(SETTING_KEYS[task], value, updated_by)
    invalidate_cache()
    logger.info("Model for task %s set to %s (fallback=%s) by %s", task, value["primary"], value["fallback"], updated_by)
