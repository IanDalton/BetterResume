# Admin Model Management & In-Dashboard Evals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the admin pick the LLM for each task at runtime from OpenRouter's live model feed, stop bad models/providers from failing user requests, and run + store the evaluation suite against candidate models from the dashboard.

**Architecture:** Model choice moves from an import-time env constant into an `app_settings` row read through a TTL-cached accessor (`llm/model_config.py`). The agent layer gains OpenRouter provider routing (`require_parameters`) plus a two-layer fallback — `FallbackModel` for transport errors and an explicit `UnexpectedModelBehavior` catch for output-retry exhaustion. The evaluation harness moves out of `tests/` into an importable `backend/evals/` package driven by `run_eval()`, which both pytest and a new admin endpoint call; every cell is persisted to `eval_runs` / `eval_results` including the generated resume JSON.

**Tech Stack:** Python 3.13, FastAPI, pydantic-ai 2.27 (`pydantic-ai-slim[google,openai]`), psycopg3 + psycopg-pool, PostgreSQL/pgvector, pytest (asyncio_mode=auto), React 18 + TypeScript + Vite + Tailwind, vitest.

**Spec:** `docs/superpowers/specs/2026-08-10-admin-model-management-design.md`

## Global Constraints

- Backend commands run from `backend/`; frontend commands from `frontend/`.
- Unit tests must never make a real model request. `tests/conftest.py` sets `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` unless `--real-ai` is passed — never weaken this. Use `TestModel` / `FunctionModel`.
- Unit tests must never require a live PostgreSQL. Patch `DBStorage._get_conn`.
- `pytest.ini` sets `asyncio_mode = auto`: async test functions need no `@pytest.mark.asyncio`.
- `DBStorage` cursors have **no** row factory — `cur.fetchall()` returns tuples. Build dicts explicitly, matching `get_generation_events` (`utils/db_storage.py:1092`).
- All new schema goes in `DBStorage.init_schema()` using `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`; it runs on every boot and must stay idempotent.
- All new admin endpoints live on the existing router in `api/routers/admin.py` (prefix `/admin`, mounted under `/resume`) and depend on `require_admin`.
- Model strings are pydantic-ai format `provider:name`, e.g. `openrouter:qwen/qwen3-coder-30b-a3b-instruct`, `google-gla:gemini-2.5-flash-lite`.
- Task names are exactly `"generation"`, `"translation"`, `"import"`. Setting keys are `model.generation`, `model.translation`, `model.import`.
- Commit after every task. Run the full `pytest` suite before each commit.

---

## File Structure

**Phase 1 — runtime config + hardening**

| File | Responsibility |
| --- | --- |
| `backend/utils/db_storage.py` (modify) | `app_settings` table + get/set accessors; `generation_events` new columns; fallback stats |
| `backend/llm/model_config.py` (create) | Sole reader/writer of model settings; TTL cache; env seeding |
| `backend/llm/agent.py` (modify) | Provider routing, two-layer fallback, config resolution |
| `backend/bot.py` (modify) | Separate generation/translation models; expose model actually used |
| `backend/api/routers/resume.py` (modify) | Record requested vs used model |
| `backend/tests/unit/test_app_settings_db.py` (create) | app_settings accessors |
| `backend/tests/unit/test_model_config.py` (create) | resolution, TTL, seeding, degradation |
| `backend/tests/unit/test_agent_fallback.py` (create) | both fallback layers + provider routing |

**Phase 2 — catalog, eval runner, storage, endpoints**

| File | Responsibility |
| --- | --- |
| `backend/llm/openrouter_catalog.py` (create) | Fetch + normalize + cache OpenRouter `/models` |
| `backend/evals/__init__.py` (create) | Package marker |
| `backend/evals/fixtures.py` (create) | JD fixtures, stub profile context, `StubVectorStore` |
| `backend/evals/evaluators/*` (move) | From `tests/evaluators/`; `LLMJudge.aevaluate` added |
| `backend/evals/runner.py` (create) | `EvalSpec`, `run_eval`, concurrency + caps |
| `backend/utils/db_storage.py` (modify) | `eval_runs` / `eval_results` tables + accessors |
| `backend/api/routers/admin.py` (modify) | Model config, catalog, and eval endpoints |
| `backend/api/main.py` (modify) | Mark orphaned running evals `interrupted` on boot |
| `backend/tests/unit/test_openrouter_catalog.py` (create) | Parsing, TTL, failure |
| `backend/tests/unit/test_eval_runner.py` (create) | Runner on `TestModel` |
| `backend/tests/unit/test_admin_models_api.py` (create) | Config + catalog endpoints |
| `backend/tests/unit/test_admin_evals_api.py` (create) | Eval endpoints |

**Phase 3 — dashboard**

| File | Responsibility |
| --- | --- |
| `frontend/src/services/api.ts` (modify) | Admin model + eval client functions |
| `frontend/src/components/admin/{StatCard,BarChart,CountTable}.tsx` (create) | Extracted from AdminDashboard |
| `frontend/src/pages/AdminDashboard.tsx` (modify) | Auth + tab shell only |
| `frontend/src/pages/admin/StatsTab.tsx` (create) | Existing dashboard body |
| `frontend/src/pages/admin/ModelsTab.tsx` (create) | Per-task model config |
| `frontend/src/components/admin/ModelPicker.tsx` (create) | Searchable catalog picker |
| `frontend/src/pages/admin/EvalsTab.tsx` (create) | New run + live grid |
| `frontend/src/components/admin/EvalResults.tsx` (create) | Results table, resume preview, history, compare |
| `frontend/src/services/__tests__/adminApi.test.ts` (create) | Client function tests |

---

# PHASE 1 — Runtime model configuration and hardening

Ship-ready on its own: it fixes the production `Exceeded maximum output retries` / provider-400 failures.

---

### Task 1: `app_settings` table and accessors

**Files:**
- Modify: `backend/utils/db_storage.py` (add table to `init_schema`, add three methods)
- Test: `backend/tests/unit/test_app_settings_db.py` (create)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `DBStorage.get_app_setting(key: str) -> Optional[dict]` — returns the stored JSON value, or `None` if absent
  - `DBStorage.set_app_setting(key: str, value: dict, updated_by: Optional[str] = None) -> None` — upsert
  - `DBStorage.get_app_settings_meta(prefix: str = "") -> Dict[str, dict]` — `{key: {"value": dict, "updated_at": str|None, "updated_by": str|None}}`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_app_settings_db.py`:

```python
"""Tests for the app_settings key/value accessors on DBStorage."""

import contextlib
import json
from unittest.mock import patch

from utils.db_storage import DBStorage


class FakeCursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *a, **k):
        return self._cursor

    def commit(self):
        pass


def _patch_conn(cursor):
    @contextlib.contextmanager
    def fake_get_conn(self):
        yield FakeConn(cursor)

    return patch.object(DBStorage, "_get_conn", fake_get_conn)


def test_get_app_setting_returns_value():
    cur = FakeCursor(rows=[({"primary": "openrouter:a", "fallback": None},)])
    with _patch_conn(cur):
        assert DBStorage().get_app_setting("model.generation") == {
            "primary": "openrouter:a",
            "fallback": None,
        }
    assert "model.generation" in cur.executed[0][1]


def test_get_app_setting_returns_none_when_missing():
    with _patch_conn(FakeCursor(rows=[])):
        assert DBStorage().get_app_setting("model.generation") is None


def test_get_app_setting_parses_json_string_value():
    """psycopg may hand back a raw JSON string depending on adapter registration."""
    cur = FakeCursor(rows=[(json.dumps({"primary": "google-gla:x", "fallback": None}),)])
    with _patch_conn(cur):
        assert DBStorage().get_app_setting("model.import")["primary"] == "google-gla:x"


def test_set_app_setting_upserts_with_actor():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().set_app_setting(
            "model.generation",
            {"primary": "openrouter:b", "fallback": "google-gla:c"},
            updated_by="admin@example.com",
        )
    sql, params = cur.executed[0]
    assert "INSERT INTO app_settings" in sql
    assert "ON CONFLICT (key) DO UPDATE" in sql
    assert params[0] == "model.generation"
    assert params[2] == "admin@example.com"


def test_get_app_settings_meta_returns_rows_by_key():
    cur = FakeCursor(rows=[
        ("model.generation", {"primary": "openrouter:b", "fallback": None}, None, "admin@example.com"),
    ])
    with _patch_conn(cur):
        meta = DBStorage().get_app_settings_meta("model.")
    assert meta["model.generation"]["value"]["primary"] == "openrouter:b"
    assert meta["model.generation"]["updated_by"] == "admin@example.com"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_app_settings_db.py -v`
Expected: FAIL — `AttributeError: 'DBStorage' object has no attribute 'get_app_setting'`

- [ ] **Step 3: Add the table to `init_schema`**

In `backend/utils/db_storage.py`, inside `init_schema()`, after the `generation_events` block (~line 358):

```python
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS app_settings (
                            key         TEXT PRIMARY KEY,
                            value       JSONB NOT NULL,
                            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_by  TEXT
                        );
                    """)
```

- [ ] **Step 4: Implement the accessors**

Add to `DBStorage`, next to `record_generation_event`:

```python
    # ------------------------------------------------------------------
    # Application settings (key/value, used for runtime model configuration)
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_json(value):
        """psycopg returns jsonb as a dict when the adapter is registered and a
        str otherwise; normalize both to a dict."""
        if value is None or isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None

    def get_app_setting(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the stored JSON value for `key`, or None if unset."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
                row = cur.fetchone()
        return self._coerce_json(row[0]) if row else None

    def set_app_setting(self, key: str, value: Dict[str, Any], updated_by: Optional[str] = None) -> None:
        """Upsert a settings row."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_by, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = NOW()
                    """,
                    (key, Json(value), updated_by),
                )
        self.logger.info("app_setting %s updated by %s", key, updated_by)

    def get_app_settings_meta(self, prefix: str = "") -> Dict[str, Dict[str, Any]]:
        """Return {key: {value, updated_at, updated_by}} for keys starting with `prefix`."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT key, value, updated_at, updated_by FROM app_settings WHERE key LIKE %s ORDER BY key",
                    (f"{prefix}%",),
                )
                rows = cur.fetchall()
        return {
            r[0]: {
                "value": self._coerce_json(r[1]),
                "updated_at": r[2].isoformat() if r[2] else None,
                "updated_by": r[3],
            }
            for r in rows
        }
```

`json` and `Json` must be importable. `json` is already imported at the top of the module; confirm and add `from psycopg.types.json import Json` to the imports if it is not already present.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_app_settings_db.py -v`
Expected: 5 passed

- [ ] **Step 6: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/utils/db_storage.py backend/tests/unit/test_app_settings_db.py
git commit -m "feat(db): add app_settings key/value table and accessors"
```

---

### Task 2: `llm/model_config.py` — TTL-cached per-task model settings

**Files:**
- Create: `backend/llm/model_config.py`
- Test: `backend/tests/unit/test_model_config.py` (create)

**Interfaces:**
- Consumes: `DBStorage.get_app_setting`, `DBStorage.set_app_setting`, `DBStorage.get_app_settings_meta` (Task 1)
- Produces:
  - `TASKS: tuple[str, ...] = ("generation", "translation", "import")`
  - `SETTING_KEYS: dict[str, str]` — task → `model.<task>`
  - `CACHE_TTL_SECONDS: float = 30.0`
  - `@dataclass(frozen=True) TaskModels(primary: str, fallback: Optional[str])`
  - `@dataclass(frozen=True) ModelConfig(generation: TaskModels, translation: TaskModels, import_: TaskModels)` with `for_task(task: str) -> TaskModels`
  - `get_model_config(force_refresh: bool = False) -> ModelConfig`
  - `set_task_models(task: str, primary: str, fallback: Optional[str], updated_by: Optional[str] = None) -> None`
  - `invalidate_cache() -> None`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_model_config.py`:

```python
"""Tests for runtime per-task model configuration."""

from unittest.mock import patch

import pytest

from llm import model_config


@pytest.fixture(autouse=True)
def _clear_cache():
    model_config.invalidate_cache()
    yield
    model_config.invalidate_cache()


def test_falls_back_to_env_when_no_row(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    monkeypatch.delenv("TRANSLATION_MODEL", raising=False)
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=None):
        cfg = model_config.get_model_config(force_refresh=True)
    assert cfg.generation.primary == "openrouter:env/primary"
    assert cfg.translation.primary == "openrouter:env/primary"


def test_env_task_override_used_when_present(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    monkeypatch.setenv("IMPORT_MODEL", "google-gla:gemini-2.5-flash-lite")
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=None):
        cfg = model_config.get_model_config(force_refresh=True)
    assert cfg.import_.primary == "google-gla:gemini-2.5-flash-lite"


def test_stored_row_overrides_env(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    stored = {"primary": "openrouter:stored/x", "fallback": "google-gla:gemini-2.5-flash-lite"}
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=stored):
        cfg = model_config.get_model_config(force_refresh=True)
    assert cfg.generation.primary == "openrouter:stored/x"
    assert cfg.generation.fallback == "google-gla:gemini-2.5-flash-lite"


def test_result_is_cached_within_ttl(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=None) as mocked:
        model_config.get_model_config(force_refresh=True)
        model_config.get_model_config()
        model_config.get_model_config()
    # 3 tasks read once each on the first (uncached) call only
    assert mocked.call_count == len(model_config.TASKS)


def test_cache_expires_after_ttl(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    fake_now = {"t": 1000.0}
    monkeypatch.setattr(model_config.time, "monotonic", lambda: fake_now["t"])
    with patch("llm.model_config.DBStorage.get_app_setting", return_value=None) as mocked:
        model_config.get_model_config(force_refresh=True)
        fake_now["t"] += model_config.CACHE_TTL_SECONDS + 1
        model_config.get_model_config()
    assert mocked.call_count == 2 * len(model_config.TASKS)


def test_db_failure_degrades_to_env(monkeypatch, caplog):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    with patch("llm.model_config.DBStorage.get_app_setting", side_effect=RuntimeError("db down")):
        cfg = model_config.get_model_config(force_refresh=True)
    assert cfg.generation.primary == "openrouter:env/primary"


def test_set_task_models_writes_and_invalidates(monkeypatch):
    monkeypatch.setenv("DEFAULT_MODEL", "openrouter:env/primary")
    with patch("llm.model_config.DBStorage.set_app_setting") as setter, \
         patch("llm.model_config.DBStorage.get_app_setting", return_value=None):
        model_config.get_model_config(force_refresh=True)
        model_config.set_task_models("generation", "openrouter:new/x", None, updated_by="a@b.c")
    args = setter.call_args.args
    assert args[0] == "model.generation"
    assert args[1] == {"primary": "openrouter:new/x", "fallback": None}
    assert model_config._CACHE["value"] is None, "write must invalidate the cache"


def test_set_task_models_rejects_unknown_task():
    with pytest.raises(ValueError):
        model_config.set_task_models("nonsense", "openrouter:x", None)


def test_set_task_models_rejects_unprefixed_model():
    with pytest.raises(ValueError):
        model_config.set_task_models("generation", "gpt-4o-mini-no-provider", None)


def test_for_task_lookup():
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("a:1", None),
        translation=model_config.TaskModels("b:2", None),
        import_=model_config.TaskModels("c:3", None),
    )
    assert cfg.for_task("import").primary == "c:3"
    with pytest.raises(ValueError):
        cfg.for_task("bogus")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_model_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.model_config'`

- [ ] **Step 3: Implement the module**

Create `backend/llm/model_config.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_model_config.py -v`
Expected: 10 passed

- [ ] **Step 5: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/llm/model_config.py backend/tests/unit/test_model_config.py
git commit -m "feat(llm): add TTL-cached per-task model configuration"
```

---

### Task 3: OpenRouter provider routing + two-layer fallback in the agent layer

This is the task that fixes the reported production errors.

**Files:**
- Modify: `backend/llm/agent.py` (`_model_settings`, `generate`, `translate`, `extract_resume_fields`, new `_run_with_fallback`)
- Test: `backend/tests/unit/test_agent_fallback.py` (create)

**Interfaces:**
- Consumes: `llm.model_config.get_model_config` (Task 2)
- Produces:
  - `agent._resolve_model(task: str, model) -> tuple[Any, Optional[str]]` — returns `(primary, fallback_or_None)`; an explicit non-None `model` argument returns `(model, None)`
  - `agent._run_with_fallback(agent_obj, prompt, *, primary, fallback, on_model_used, **run_kwargs)` — returns the pydantic-ai `AgentRunResult`
  - `generate(..., on_model_used: Optional[Callable[[str, bool], None]] = None)` — same for `translate` and `extract_resume_fields`; the callback receives `(model_string_used, fallback_used)`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_agent_fallback.py`:

```python
"""Tests for OpenRouter provider routing and the two-layer model fallback.

Layer 1 — FallbackModel handles ModelAPIError (transport/provider 400s).
Layer 2 — an explicit UnexpectedModelBehavior catch handles output-retry
exhaustion, which is raised in pydantic_ai._agent_graph above the model layer
where FallbackModel cannot see it. This is the exact production failure:
"Exceeded maximum output retries (3)".
"""

from unittest.mock import patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from llm import agent, model_config


class FakeDB:
    def get_job_experiences(self, user_id, type_filter=None):
        return [{"company": "Acme Corp", "start_date": "2021-03-01", "end_date": "2024-01-01"}]


def _output_only_model(resume_args):
    """Answers immediately without calling search_experience."""
    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        output_tool = next(t.name for t in info.output_tools)
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args=resume_args)])
    return FunctionModel(model_fn)


def _retrieving_model(resume_args):
    """Calls search_experience once, then answers."""
    state = {"searched": False}

    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        output_tool = next(t.name for t in info.output_tools)
        if not state["searched"]:
            state["searched"] = True
            return ModelResponse(parts=[ToolCallPart(tool_name="search_experience", args={"query": "python"})])
        return ModelResponse(parts=[ToolCallPart(tool_name=output_tool, args=resume_args)])

    return FunctionModel(model_fn)


def _raising_model(exc):
    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        raise exc
    return FunctionModel(model_fn)


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------

def test_openrouter_settings_require_parameters():
    """Providers that cannot accept our tool-call params must be routed around."""
    settings = agent._model_settings("openrouter:qwen/qwen3-coder-30b-a3b-instruct")
    assert settings["openrouter_provider"]["require_parameters"] is True
    assert settings["openrouter_reasoning"] == {"enabled": False}


def test_non_openrouter_settings_untouched():
    assert agent._model_settings("google-gla:gemini-2.5-flash-lite") is None


# ---------------------------------------------------------------------------
# Layer 2: output-retry exhaustion (the reported production error)
# ---------------------------------------------------------------------------

async def test_falls_back_when_primary_exhausts_output_retries(stub_vector_store, sample_resume_output):
    resume_args = sample_resume_output.model_dump()
    seen = {}

    resume = await agent.generate(
        "Backend role",
        user_id="u1",
        vector_store=stub_vector_store,
        db=FakeDB(),
        model=_output_only_model(resume_args),          # never retrieves -> ModelRetry x3
        fallback_model=_retrieving_model(resume_args),  # retrieves -> succeeds
        require_tool_call=True,
        on_model_used=lambda name, fallback: seen.update(name=name, fallback=fallback),
    )

    assert resume.language == "en"
    assert seen["fallback"] is True


async def test_no_fallback_configured_propagates_original_error(stub_vector_store, sample_resume_output):
    with pytest.raises(UnexpectedModelBehavior, match="Exceeded maximum output retries"):
        await agent.generate(
            "Backend role",
            user_id="u1",
            vector_store=stub_vector_store,
            db=FakeDB(),
            model=_output_only_model(sample_resume_output.model_dump()),
            fallback_model=None,
            require_tool_call=True,
        )


async def test_failing_fallback_propagates_original_error(stub_vector_store, sample_resume_output):
    """When the fallback fails too, the caller sees the primary's failure."""
    with pytest.raises(UnexpectedModelBehavior, match="Exceeded maximum output retries"):
        await agent.generate(
            "Backend role",
            user_id="u1",
            vector_store=stub_vector_store,
            db=FakeDB(),
            model=_output_only_model(sample_resume_output.model_dump()),
            fallback_model=_output_only_model(sample_resume_output.model_dump()),
            require_tool_call=True,
        )


# ---------------------------------------------------------------------------
# Layer 1: transport / provider errors
# ---------------------------------------------------------------------------

async def test_falls_back_on_model_http_error(stub_vector_store, sample_resume_output):
    resume_args = sample_resume_output.model_dump()
    seen = {}

    resume = await agent.generate(
        "Backend role",
        user_id="u1",
        vector_store=stub_vector_store,
        db=FakeDB(),
        model=_raising_model(ModelHTTPError(status_code=400, model_name="bad", body="Provider returned error")),
        fallback_model=_retrieving_model(resume_args),
        require_tool_call=True,
        on_model_used=lambda name, fallback: seen.update(name=name, fallback=fallback),
    )

    assert resume.language == "en"
    assert seen["fallback"] is True


# ---------------------------------------------------------------------------
# Happy path reports no fallback
# ---------------------------------------------------------------------------

async def test_success_reports_primary_and_no_fallback(stub_vector_store, sample_resume_output):
    resume_args = sample_resume_output.model_dump()
    seen = {}

    await agent.generate(
        "Backend role",
        user_id="u1",
        vector_store=stub_vector_store,
        db=FakeDB(),
        model=_retrieving_model(resume_args),
        fallback_model=_retrieving_model(resume_args),
        require_tool_call=True,
        on_model_used=lambda name, fallback: seen.update(name=name, fallback=fallback),
    )

    assert seen["fallback"] is False


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

async def test_model_none_resolves_from_config(stub_vector_store, sample_resume_output):
    """model=None must consult model_config, not the DEFAULT_MODEL constant."""
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:configured/primary", "openrouter:configured/fallback"),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
    )
    with patch("llm.agent.get_model_config", return_value=cfg):
        primary, fallback = agent._resolve_model("generation", None)
    assert primary == "openrouter:configured/primary"
    assert fallback == "openrouter:configured/fallback"


def test_explicit_model_bypasses_config():
    with patch("llm.agent.get_model_config", side_effect=AssertionError("must not be consulted")):
        primary, fallback = agent._resolve_model("generation", "google-gla:gemini-2.5-flash-lite")
    assert primary == "google-gla:gemini-2.5-flash-lite"
    assert fallback is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_agent_fallback.py -v`
Expected: FAIL — `AttributeError: module 'llm.agent' has no attribute '_resolve_model'`, and `generate()` rejecting `fallback_model`

- [ ] **Step 3: Implement provider routing and fallback in `llm/agent.py`**

Replace `_model_settings` (lines 70-83) with:

```python
def _model_settings(model: Union[str, Model]) -> Optional[dict]:
    """Per-model run settings.

    For OpenRouter: disable reasoning tokens (latency), and set
    `require_parameters` so OpenRouter only routes to providers that accept the
    tool-call/structured-output parameters we send. Without it, requests get
    routed to providers that reject them outright (observed 400s from Alibaba,
    SiliconFlow, DigitalOcean) or return malformed tool arguments that burn all
    of the agent's output retries.

    Returns ``None`` for non-OpenRouter models so their defaults are untouched.
    """
    if isinstance(model, str):
        is_openrouter = model.startswith("openrouter:")
    else:
        is_openrouter = type(model).__name__ == "OpenRouterModel"
    if not is_openrouter:
        return None
    from pydantic_ai.models.openrouter import OpenRouterModelSettings

    return OpenRouterModelSettings(
        openrouter_reasoning={"enabled": False},
        openrouter_provider={"require_parameters": True},
    )
```

Add near the imports:

```python
from typing import Callable
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior

from llm.model_config import get_model_config
```

Add the resolution + fallback helpers after `_model_settings`:

```python
def _resolve_model(task: str, model: Union[str, Model, None]) -> Tuple[Union[str, Model], Optional[str]]:
    """Resolve (primary, fallback) for a task.

    An explicit `model` always wins and never gets a fallback — that is what the
    eval runner and the tests pass, and they must exercise exactly the model
    they asked for.
    """
    if model is not None:
        return normalize_model_name(model), None
    task_models = get_model_config().for_task(task)
    fallback = task_models.fallback
    return (
        normalize_model_name(task_models.primary),
        normalize_model_name(fallback) if fallback else None,
    )


def _model_label(model: Union[str, Model]) -> str:
    return model if isinstance(model, str) else getattr(model, "model_name", type(model).__name__)


async def _run_with_fallback(
    agent_obj: Agent,
    prompt: Any,
    *,
    primary: Union[str, Model],
    fallback: Union[str, Model, None],
    on_model_used: Optional[Callable[[str, bool], None]] = None,
    **run_kwargs,
):
    """Run `agent_obj` on `primary`, falling back to `fallback` on failure.

    Two distinct failure modes need two mechanisms:

    1. Transport/provider errors (`ModelAPIError`, which `ModelHTTPError`
       subclasses) are handled by `FallbackModel`, inside the model layer.
    2. Output-retry exhaustion raises `UnexpectedModelBehavior` from
       `pydantic_ai._agent_graph`, *above* the model layer, where FallbackModel
       never sees it. That needs the explicit re-run below.
    """
    def _report(model, used_fallback: bool):
        if on_model_used:
            on_model_used(_model_label(model), used_fallback)

    if fallback is None:
        result = await agent_obj.run(prompt, model=primary, model_settings=_model_settings(primary), **run_kwargs)
        _report(primary, False)
        return result

    from pydantic_ai.models.fallback import FallbackModel

    layered = FallbackModel(primary, fallback, fallback_on=(ModelAPIError,))
    try:
        result = await agent_obj.run(prompt, model=layered, model_settings=_model_settings(primary), **run_kwargs)
    except UnexpectedModelBehavior as exc:
        logger.warning(
            "Primary model %s failed output validation (%s); retrying on fallback %s",
            _model_label(primary), exc, _model_label(fallback),
        )
        try:
            result = await agent_obj.run(
                prompt, model=fallback, model_settings=_model_settings(fallback), **run_kwargs
            )
        except Exception:
            logger.warning("Fallback model %s also failed; surfacing the primary error", _model_label(fallback))
            raise exc
        _report(fallback, True)
        return result

    used = getattr(result, "model_name", None) or _model_label(primary)
    used_fallback = used != _model_label(primary)
    if used_fallback:
        logger.warning("Primary model %s unavailable; served by fallback %s", _model_label(primary), used)
    _report(used, used_fallback)
    return result
```

Note on the last block: `FallbackModel` reports the model that actually answered via the run result's `model_name`. If that attribute is absent on this pydantic-ai version, derive it from `result.all_messages()[-1].model_name`; the tests pin the behaviour either way.

Now rewrite the three entry points. `generate`:

```python
async def generate(
    jd: str,
    *,
    user_id: str,
    vector_store: Any = None,
    db: Any = None,
    model: Union[str, Model, None] = None,
    fallback_model: Union[str, Model, None] = None,
    require_tool_call: bool = True,
    extra_context: Optional[str] = None,
    on_model_used: Optional[Callable[[str, bool], None]] = None,
) -> ResumeOutputFormat:
    """Generate a structured resume for a job description.

    Args:
        model: explicit model; when None, resolved from runtime configuration.
        fallback_model: explicit fallback; when None and `model` is None, the
            configured fallback for the generation task is used.
        extra_context: Authoritative facts (current date, computed years of
            experience, spoken languages) appended to the prompt so the model
            stays consistent with the user's stored data.
        on_model_used: called with (model_string, fallback_used) once the run
            succeeds, so callers can record what actually served the request.
    """
    primary, configured_fallback = _resolve_model("generation", model)
    fallback = normalize_model_name(fallback_model) if fallback_model is not None else configured_fallback
    deps = ResumeDeps(
        user_id=user_id,
        vector_store=vector_store,
        db=db,
        require_tool_call=require_tool_call,
    )
    start = time.monotonic()
    logger.info("Generation start user=%s model=%s fallback=%s jd_chars=%d",
                user_id, primary, fallback, len(jd or ""))
    prompt = jd if not extra_context else f"{jd}\n\n{extra_context}"
    result = await _run_with_fallback(
        generation_agent, prompt,
        primary=primary, fallback=fallback, on_model_used=on_model_used, deps=deps,
    )
    logger.info(
        "Generation finished user=%s in %dms; searches=%d",
        user_id, int((time.monotonic() - start) * 1000), deps.search_calls,
    )
    _log_usage("Generation", result)
    return result.output
```

Apply the same shape to `translate` (task `"translation"`, agent `translation_agent`, no `deps`) and `extract_resume_fields` (task `"import"`, agent `resume_import_agent`, no `deps`), each gaining `fallback_model` and `on_model_used` parameters.

Leave `DEFAULT_MODEL` and `normalize_model_name` exactly as they are — `normalize_model_name(None)` still returns `DEFAULT_MODEL`, which existing tests assert.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_agent_fallback.py tests/unit/test_agent.py -v`
Expected: all pass (11 new + 11 existing)

- [ ] **Step 5: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/llm/agent.py backend/tests/unit/test_agent_fallback.py
git commit -m "fix(llm): route OpenRouter around incapable providers and add model fallback"
```

---

### Task 4: Bot — separate generation/translation models, report the model used

**Files:**
- Modify: `backend/bot.py` (`__init__`, `_pipeline`, `translate_resume`)
- Modify: `backend/tests/unit/test_bot.py` (only if it asserts on `bot.model`)
- Test: `backend/tests/unit/test_bot_models.py` (create)

**Interfaces:**
- Consumes: `agent.generate(..., on_model_used=)`, `agent._resolve_model` (Task 3)
- Produces:
  - `Bot.generation_model` / `Bot.translation_model` — resolved at init
  - `Bot.model` — read-only property aliasing `generation_model` (back-compat)
  - `Bot.last_model_used: Optional[str]` / `Bot.last_fallback_used: bool` — set after a run

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_bot_models.py`:

```python
"""Bot resolves generation and translation models independently and records
which model actually served the run."""

from unittest.mock import patch

from bot import Bot
from llm import model_config


def _cfg(gen="openrouter:gen/x", trans="google-gla:gemini-2.5-flash-lite"):
    return model_config.ModelConfig(
        generation=model_config.TaskModels(gen, "openrouter:gen/fb"),
        translation=model_config.TaskModels(trans, None),
        import_=model_config.TaskModels("openrouter:imp/x", None),
    )


def test_models_resolved_per_task_from_config():
    with patch("llm.agent.get_model_config", return_value=_cfg()):
        bot = Bot(user_id="u1", auto_ingest=False)
    assert bot.generation_model == "openrouter:gen/x"
    assert bot.translation_model == "google-gla:gemini-2.5-flash-lite"
    assert bot.model == bot.generation_model


def test_explicit_model_applies_to_both_tasks():
    bot = Bot(user_id="u1", model="google-gla:gemini-2.5-flash-lite", auto_ingest=False)
    assert bot.generation_model == "google-gla:gemini-2.5-flash-lite"
    assert bot.translation_model == "google-gla:gemini-2.5-flash-lite"


async def test_generate_records_model_used(stub_vector_store, sample_resume_output):
    from pydantic_ai.models.test import TestModel

    bot = Bot(
        user_id="u1",
        vector_store=stub_vector_store,
        model=TestModel(custom_output_args=sample_resume_output.model_dump()),
        db=None,
        auto_ingest=False,
    )
    with patch.object(Bot, "_fetch_generation_context", return_value=None):
        await bot.generate_resume("Backend role")

    assert bot.last_model_used is not None
    assert bot.last_fallback_used is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_bot_models.py -v`
Expected: FAIL — `AttributeError: 'Bot' object has no attribute 'generation_model'`

- [ ] **Step 3: Implement**

In `backend/bot.py` `__init__`, replace `self.model = agent.normalize_model_name(model)` with:

```python
        # Explicit model applies to every task (eval runs, tests, CLI). With no
        # explicit model, each task resolves independently from runtime config.
        self.generation_model, self._generation_fallback = agent._resolve_model("generation", model)
        self.translation_model, self._translation_fallback = agent._resolve_model("translation", model)
        self.last_model_used: Optional[str] = None
        self.last_fallback_used: bool = False
```

and update the init log line to use `self.generation_model`. Add the back-compat property after `__init__`:

```python
    @property
    def model(self):
        """Back-compat alias: the generation model."""
        return self.generation_model
```

In `_pipeline`, replace the `agent.generate(...)` call's `model=self.model` with:

```python
        resume = await agent.generate(
            jd,
            user_id=self.user_id,
            vector_store=self.vector_store,
            db=self.db,
            model=self.generation_model,
            fallback_model=self._generation_fallback,
            require_tool_call=True,
            extra_context=extra_context,
            on_model_used=self._record_model_used,
        )
```

Add the recorder method:

```python
    def _record_model_used(self, model_name: str, fallback_used: bool) -> None:
        self.last_model_used = model_name
        self.last_fallback_used = self.last_fallback_used or fallback_used
```

In `translate_resume`, use the translation model:

```python
        return await agent.translate(
            r, original_jd,
            user_id=self.user_id,
            model=self.translation_model,
            fallback_model=self._translation_fallback,
            on_model_used=self._record_model_used,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_bot_models.py tests/unit/test_bot.py -v`
Expected: all pass. If `test_bot.py` asserts on `bot.model`, the property keeps it green; if it *sets* `bot.model`, change those lines to set `generation_model`.

- [ ] **Step 5: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/bot.py backend/tests/unit/test_bot_models.py backend/tests/unit/test_bot.py
git commit -m "feat(bot): resolve generation and translation models independently"
```

---

### Task 5: Record requested vs used model and surface the fallback rate

**Files:**
- Modify: `backend/utils/db_storage.py` (`init_schema`, `record_generation_event`, `get_admin_stats`, `get_generation_events`)
- Modify: `backend/api/routers/resume.py` (`_record_generation` and its four call sites: lines 179, 181, 314, 333)
- Modify: `backend/api/routers/admin.py` (CSV export field list, line 36)
- Test: `backend/tests/unit/test_generation_events.py` (create)

**Interfaces:**
- Consumes: `Bot.last_model_used`, `Bot.last_fallback_used` (Task 4)
- Produces:
  - `DBStorage.record_generation_event(..., requested_model: Optional[str] = None, fallback_used: bool = False)`
  - `get_admin_stats()["totals"]["fallback_generations"]` and `["fallback_rate"]` (float or `None`)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_generation_events.py`:

```python
"""Generation events record the requested model alongside the model that served
the request, so a silently-degrading primary is visible on the dashboard."""

import contextlib
from unittest.mock import patch

from utils.db_storage import DBStorage
from tests.unit.test_app_settings_db import FakeConn, FakeCursor


def _patch_conn(cursor):
    @contextlib.contextmanager
    def fake_get_conn(self):
        yield FakeConn(cursor)

    return patch.object(DBStorage, "_get_conn", fake_get_conn)


def test_record_generation_event_persists_fallback_columns():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().record_generation_event(
            user_id="u1",
            model="google-gla:gemini-2.5-flash-lite",
            requested_model="openrouter:qwen/qwen3-coder-30b-a3b-instruct",
            format="word",
            language="en",
            duration_ms=1234,
            status="success",
            fallback_used=True,
        )
    sql, params = cur.executed[0]
    assert "requested_model" in sql and "fallback_used" in sql
    assert "openrouter:qwen/qwen3-coder-30b-a3b-instruct" in params
    assert True in params


def test_record_generation_event_defaults_are_backwards_compatible():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().record_generation_event(user_id="u1", model="m", status="success")
    _, params = cur.executed[0]
    assert False in params, "fallback_used must default to False"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_generation_events.py -v`
Expected: FAIL — `TypeError: record_generation_event() got an unexpected keyword argument 'requested_model'`

- [ ] **Step 3: Implement**

In `init_schema()`, right after the `generation_events` `CREATE TABLE`:

```python
                    cur.execute("ALTER TABLE generation_events ADD COLUMN IF NOT EXISTS requested_model TEXT;")
                    cur.execute("ALTER TABLE generation_events ADD COLUMN IF NOT EXISTS fallback_used BOOLEAN NOT NULL DEFAULT FALSE;")
```

Extend `record_generation_event` with `requested_model: Optional[str] = None` and `fallback_used: bool = False` parameters, and widen the INSERT:

```python
                    cur.execute(
                        """
                        INSERT INTO generation_events
                            (user_id, model, requested_model, format, language, duration_ms, status, error, fallback_used)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, model, requested_model, format, language, duration_ms, status,
                         (error or None) and str(error)[:2000], bool(fallback_used)),
                    )
```

In `get_admin_stats`, alongside the existing generation totals, add:

```python
                cur.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE fallback_used),
                           COUNT(*)
                    FROM generation_events
                    WHERE created_at >= NOW() - (%s || ' days')::interval
                    """,
                    (days,),
                )
                fb_row = cur.fetchone() or (0, 0)
                fallback_count, event_count = int(fb_row[0] or 0), int(fb_row[1] or 0)
                stats["totals"]["fallback_generations"] = fallback_count
                stats["totals"]["fallback_rate"] = round(fallback_count / event_count, 4) if event_count else None
```

Match the surrounding style in `get_admin_stats` for how the cursor and `days` interval are used — copy the interval expression from the neighbouring query rather than inventing one.

Add `requested_model` and `fallback_used` to the `SELECT` in `get_generation_events` and to its result dicts, then to the CSV `fields` list in `api/routers/admin.py:36`:

```python
    fields = ["id", "created_at", "user_id", "model", "requested_model", "fallback_used",
              "format", "language", "duration_ms", "status", "error"]
```

In `api/routers/resume.py`, widen `_record_generation`:

```python
def _record_generation(user_id, model, fmt, language, started_at, status, error=None,
                       requested_model=None, fallback_used=False):
    """Persist a generation event for admin statistics; never raises."""
    try:
        DBStorage().record_generation_event(
            user_id=user_id,
            model=str(model or ""),
            requested_model=str(requested_model or "") or None,
            format=fmt,
            language=language,
            duration_ms=int((time.time() - started_at) * 1000),
            status=status,
            error=error,
            fallback_used=bool(fallback_used),
        )
    except Exception:
        logger.warning("Failed to record generation event for user_id=%s", user_id, exc_info=True)
```

Update all four call sites to pass what the bot actually used, e.g. line 181 becomes:

```python
    _record_generation(
        user_id, bot.last_model_used or bot.generation_model, fmt, result.language, gen_start, "success",
        requested_model=bot.generation_model, fallback_used=bot.last_fallback_used,
    )
```

and the error sites (lines 179, 333) pass `requested_model=bot.generation_model` with `bot.last_model_used or bot.generation_model` as `model`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_generation_events.py tests/unit/test_admin_api.py -v`
Expected: all pass

- [ ] **Step 5: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/utils/db_storage.py backend/api/routers/resume.py backend/api/routers/admin.py backend/tests/unit/test_generation_events.py
git commit -m "feat(admin): record requested vs served model and expose fallback rate"
```

---

### Task 6: Phase 1 documentation and env template

**Files:**
- Modify: `backend/.env.template`
- Modify: `backend/CLAUDE.md`
- Modify: `CLAUDE.md` (root)

- [ ] **Step 1: Update `.env.template`**

Replace the `DEFAULT_MODEL` block with:

```
# LLM models (provider-prefixed). These SEED the runtime configuration stored in
# the app_settings table; once the admin dashboard sets a model, the stored value
# wins and these are only used as a last resort (e.g. database unreachable).
DEFAULT_MODEL=openrouter:wafer/fp4
# Optional per-task overrides; each defaults to DEFAULT_MODEL.
# TRANSLATION_MODEL=
# IMPORT_MODEL=
# Optional fallback models used when the primary fails.
# GENERATION_FALLBACK_MODEL=google-gla:gemini-2.5-flash-lite
# TRANSLATION_FALLBACK_MODEL=
# IMPORT_FALLBACK_MODEL=
```

- [ ] **Step 2: Update `backend/CLAUDE.md`**

In the "LLM / Agent Layer" section, add:

```markdown
- `model_config.py` — runtime per-task model settings (`generation` / `translation` / `import`), stored in the `app_settings` table and TTL-cached for 30s. Env vars (`DEFAULT_MODEL`, `TRANSLATION_MODEL`, `IMPORT_MODEL`, `*_FALLBACK_MODEL`) seed the values and are the last resort if the database is unreachable; a stored value always wins.
```

and extend the `agent.py` bullet with:

```markdown
  OpenRouter runs set `openrouter_provider={"require_parameters": True}` so OpenRouter skips providers that reject our tool-call parameters. Failures are covered in two layers: `FallbackModel` for `ModelAPIError`, plus an explicit `UnexpectedModelBehavior` catch for output-retry exhaustion (raised above the model layer, where FallbackModel cannot see it).
```

Update the Configuration section to mention `app_settings`.

- [ ] **Step 3: Update the root `CLAUDE.md`**

In "Key subsystems", add the `llm/model_config.py` line and note that the model is runtime-configurable rather than env-fixed.

- [ ] **Step 4: Commit**

```bash
git add backend/.env.template backend/CLAUDE.md CLAUDE.md
git commit -m "docs: document runtime model configuration and fallback behaviour"
```

**Phase 1 is deployable here.** Verify manually before continuing: start the stack (`cd backend && docker-compose up`), generate a resume, confirm `generation_events` has `requested_model` populated and `fallback_used=false`.

---

# PHASE 2 — Catalog, eval runner, storage, endpoints

---

### Task 7: OpenRouter model catalog

**Files:**
- Create: `backend/llm/openrouter_catalog.py`
- Test: `backend/tests/unit/test_openrouter_catalog.py` (create)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `class CatalogUnavailable(RuntimeError)`
  - `@dataclass(frozen=True) CatalogModel` with fields `id, model_string, name, context_length, prompt_price, completion_price, supports_tools, supports_structured_outputs` and `as_dict() -> dict`
  - `async def fetch_models(force_refresh: bool = False) -> List[CatalogModel]`
  - `def invalidate_cache() -> None`
  - `CACHE_TTL_SECONDS: float = 3600.0`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_openrouter_catalog.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_openrouter_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.openrouter_catalog'`

- [ ] **Step 3: Implement**

Create `backend/llm/openrouter_catalog.py`:

```python
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
    except Exception as exc:
        logger.warning("OpenRouter model feed unavailable: %s", exc)
        raise CatalogUnavailable(str(exc)) from exc

    models = [m for m in (_parse_entry(e) for e in payload.get("data") or []) if m is not None]
    models.sort(key=lambda m: m.id)
    _CACHE["value"] = models
    _CACHE["at"] = now
    logger.info("Fetched %d models from OpenRouter", len(models))
    return models


def invalidate_cache() -> None:
    _CACHE["value"] = None
    _CACHE["at"] = 0.0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_openrouter_catalog.py -v`
Expected: 9 passed

- [ ] **Step 5: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/llm/openrouter_catalog.py backend/tests/unit/test_openrouter_catalog.py
git commit -m "feat(llm): add cached OpenRouter model catalog"
```

---

### Task 8: Move the eval harness into an importable `evals/` package

Pure move plus one added method. No behaviour changes.

**Files:**
- Create: `backend/evals/__init__.py`, `backend/evals/fixtures.py`
- Move: `backend/tests/evaluators/*` → `backend/evals/evaluators/*`
- Modify: `backend/tests/conftest.py`, `backend/tests/unit/test_evaluators.py`, `backend/tests/integration/test_multi_model.py`, `backend/tests/integration/test_resume_generation.py`, `backend/tests/integration/test_resume_import_real.py`
- Keep: `backend/tests/fixtures/` (resume/import samples stay; only the JDs move)

**Interfaces:**
- Produces:
  - `evals.fixtures.STUB_RESUME_CONTEXT: str`
  - `evals.fixtures.StubVectorStore` — same class currently in `tests/conftest.py`
  - `evals.fixtures.JD_FIXTURES: Dict[str, JDFixture]` where `@dataclass JDFixture(id: str, label: str, text: str)`
  - `evals.fixtures.list_fixtures() -> List[dict]` — `[{"id", "label", "preview"}]`, preview = first 160 chars
  - `evals.evaluators.SchemaEvaluator`, `ATSEvaluator`, `LLMJudge`, `ResumeEvaluationReport`, `print_comparison_table` re-exported from `evals/evaluators/__init__.py`
  - `LLMJudge.aevaluate(resume, job_description) -> LLMJudgeResult` (async)

- [ ] **Step 1: Move the files with git**

```bash
cd backend
mkdir -p evals
git mv tests/evaluators evals/evaluators
touch evals/__init__.py
```

- [ ] **Step 2: Create `backend/evals/fixtures.py`**

Move `_STUB_RESUME_CONTEXT` and `StubVectorStore` verbatim out of `tests/conftest.py` (lines 27-73) and the three `JD_*` constants out of `tests/fixtures/job_descriptions.py`, then add:

```python
"""Deterministic inputs for evaluation runs.

Shared by the pytest integration tests and the admin dashboard's eval runner,
so a dashboard run and a CLI run measure exactly the same thing.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class JDFixture:
    id: str
    label: str
    text: str


JD_FIXTURES: Dict[str, JDFixture] = {
    "senior_swe": JDFixture("senior_swe", "Senior Software Engineer", JD_SOFTWARE_ENGINEER_SENIOR),
    "junior_analyst": JDFixture("junior_analyst", "Junior Data Analyst", JD_DATA_ANALYST_JUNIOR),
    "product_manager": JDFixture("product_manager", "Product Manager", JD_PRODUCT_MANAGER),
}

CUSTOM_JD_ID = "custom"


def list_fixtures() -> List[dict]:
    return [
        {"id": f.id, "label": f.label, "preview": " ".join(f.text.split())[:160]}
        for f in JD_FIXTURES.values()
    ]
```

Keep `tests/fixtures/job_descriptions.py` as a re-export so nothing else breaks:

```python
from evals.fixtures import (  # noqa: F401
    JD_SOFTWARE_ENGINEER_SENIOR,
    JD_DATA_ANALYST_JUNIOR,
    JD_PRODUCT_MANAGER,
)
```

- [ ] **Step 3: Point `tests/conftest.py` at the moved code**

Replace the deleted `_STUB_RESUME_CONTEXT` / `StubVectorStore` definitions with:

```python
from evals.fixtures import StubVectorStore  # noqa: F401  (re-exported for tests)
```

The `stub_vector_store` fixture body stays as-is.

- [ ] **Step 4: Update imports in the moved and dependent modules**

- `evals/evaluators/llm_judge.py`: `from llm.agent import normalize_model_name` is unchanged (absolute import already).
- `evals/evaluators/report.py`: relative imports unchanged.
- `evals/evaluators/__init__.py`: add the re-exports listed in the Interfaces block.
- `tests/unit/test_evaluators.py`, `tests/integration/test_multi_model.py`, `tests/integration/test_resume_generation.py`, `tests/integration/test_resume_import_real.py`: change `from tests.evaluators.X import Y` to `from evals.evaluators.X import Y`.

Verify with: `cd backend && grep -rn "tests.evaluators" . --include=*.py` → no results.

- [ ] **Step 5: Add `LLMJudge.aevaluate`**

In `evals/evaluators/llm_judge.py`, add alongside `evaluate`:

```python
    async def aevaluate(self, resume: ResumeOutputFormat, job_description: str) -> LLMJudgeResult:
        """Async variant. Required by the API-triggered runner: `run_sync` raises
        when called from inside a running event loop."""
        result = await self._agent.run(self._user_message(resume, job_description))
        return self._from_scores(result.output)
```

and factor the prompt construction out of `evaluate` into:

```python
    @staticmethod
    def _user_message(resume: ResumeOutputFormat, job_description: str) -> str:
        return (
            f"JOB DESCRIPTION:\n{job_description}\n\n"
            f"RESUME JSON:\n{resume.model_dump_json(indent=2)}\n\n"
            "Evaluate the resume."
        )
```

so `evaluate` and `aevaluate` cannot drift.

- [ ] **Step 6: Add a test for the async judge**

Append to `backend/tests/unit/test_evaluators.py`:

```python
async def test_llm_judge_aevaluate_uses_agent(sample_resume_output):
    from pydantic_ai.models.test import TestModel
    from evals.evaluators.llm_judge import LLMJudge

    judge = LLMJudge(judge_model=TestModel(custom_output_args={
        "relevance": 8, "quality": 7, "coherence": 9, "reasoning": "Solid match.",
    }))
    result = await judge.aevaluate(sample_resume_output, "Senior Python engineer")

    assert result.relevance_score == 0.8
    assert result.overall_score == pytest.approx((0.8 + 0.7 + 0.9) / 3, abs=1e-3)
```

`LLMJudge.__init__` currently normalizes a string; make sure it passes a `Model` instance straight through to `Agent` (it already does, via `normalize_model_name`).

- [ ] **Step 7: Run the tests**

Run: `cd backend && pytest -q`
Expected: everything passes, same count as before plus one.

- [ ] **Step 8: Commit**

```bash
git add -A backend/evals backend/tests
git commit -m "refactor(evals): move evaluation harness into an importable package"
```

---

### Task 9: Eval run storage

**Files:**
- Modify: `backend/utils/db_storage.py` (tables + accessors)
- Test: `backend/tests/unit/test_eval_storage.py` (create)

**Interfaces:**
- Produces on `DBStorage`:
  - `create_eval_run(run_id: str, created_by: str, data_source: str, judge_model: Optional[str], models: list, jd_ids: list, custom_jd: Optional[str], notes: Optional[str]) -> None` (status `running`)
  - `finish_eval_run(run_id: str, status: str) -> None` (sets `finished_at = NOW()`)
  - `insert_eval_result(result: dict) -> None` — keys match the `eval_results` columns minus `created_at`
  - `list_eval_runs(limit: int = 50, offset: int = 0) -> List[dict]`
  - `get_eval_run(run_id: str) -> Optional[dict]`
  - `get_eval_results(run_id: str) -> List[dict]`
  - `get_eval_result(result_id: str) -> Optional[dict]`
  - `get_eval_model_comparison() -> List[dict]` — per model: `runs`, `cells`, `success_rate`, `avg_composite`, `avg_schema`, `avg_ats`, `avg_judge`, `avg_duration_ms`, `last_run_at`
  - `mark_running_evals_interrupted() -> int`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_eval_storage.py`:

```python
"""Tests for eval run/result persistence."""

import contextlib
from unittest.mock import patch

from utils.db_storage import DBStorage
from tests.unit.test_app_settings_db import FakeConn, FakeCursor


def _patch_conn(cursor):
    @contextlib.contextmanager
    def fake_get_conn(self):
        yield FakeConn(cursor)

    return patch.object(DBStorage, "_get_conn", fake_get_conn)


def test_create_eval_run_inserts_running_status():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().create_eval_run(
            run_id="11111111-1111-1111-1111-111111111111",
            created_by="admin@example.com",
            data_source="fixture",
            judge_model="google-gla:gemini-2.5-flash-lite",
            models=["openrouter:a", "openrouter:b"],
            jd_ids=["senior_swe"],
            custom_jd=None,
            notes=None,
        )
    sql, params = cur.executed[0]
    assert "INSERT INTO eval_runs" in sql
    assert "running" in params


def test_finish_eval_run_sets_status_and_timestamp():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().finish_eval_run("11111111-1111-1111-1111-111111111111", "complete")
    sql, params = cur.executed[0]
    assert "UPDATE eval_runs" in sql and "finished_at = NOW()" in sql
    assert params[0] == "complete"


def test_insert_eval_result_persists_resume_json():
    cur = FakeCursor()
    with _patch_conn(cur):
        DBStorage().insert_eval_result({
            "id": "22222222-2222-2222-2222-222222222222",
            "run_id": "11111111-1111-1111-1111-111111111111",
            "model": "openrouter:a",
            "jd_id": "senior_swe",
            "status": "success",
            "error": None,
            "duration_ms": 4200,
            "input_tokens": 900,
            "output_tokens": 700,
            "fallback_used": False,
            "schema_score": 1.0,
            "schema_passed": True,
            "schema_errors": [],
            "ats_score": 0.8,
            "ats_coverage": 0.75,
            "missing_keywords": ["airflow"],
            "judge_overall": 0.82,
            "judge_relevance": 0.8,
            "judge_quality": 0.8,
            "judge_coherence": 0.9,
            "judge_reasoning": "Good.",
            "composite_score": 0.87,
            "resume_json": {"language": "en"},
        })
    sql, _ = cur.executed[0]
    assert "INSERT INTO eval_results" in sql
    assert "resume_json" in sql


def test_get_eval_results_builds_dicts():
    cur = FakeCursor(rows=[(
        "22222222-2222-2222-2222-222222222222", "11111111-1111-1111-1111-111111111111",
        "openrouter:a", "senior_swe", "success", None, 4200, 900, 700, False,
        1.0, True, [], 0.8, 0.75, ["airflow"], 0.82, 0.8, 0.8, 0.9, "Good.", 0.87,
        {"language": "en"}, None,
    )])
    with _patch_conn(cur):
        results = DBStorage().get_eval_results("11111111-1111-1111-1111-111111111111")
    assert results[0]["model"] == "openrouter:a"
    assert results[0]["resume_json"] == {"language": "en"}
    assert results[0]["composite_score"] == 0.87


def test_mark_running_evals_interrupted():
    cur = FakeCursor(rows=[(3,)])
    with _patch_conn(cur):
        DBStorage().mark_running_evals_interrupted()
    sql, _ = cur.executed[0]
    assert "UPDATE eval_runs" in sql and "interrupted" in sql
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_eval_storage.py -v`
Expected: FAIL — `AttributeError: 'DBStorage' object has no attribute 'create_eval_run'`

- [ ] **Step 3: Add the tables to `init_schema`**

After the `app_settings` block:

```python
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS eval_runs (
                            id           UUID PRIMARY KEY,
                            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            finished_at  TIMESTAMPTZ,
                            created_by   TEXT NOT NULL,
                            status       TEXT NOT NULL,
                            data_source  TEXT NOT NULL,
                            judge_model  TEXT,
                            models       JSONB NOT NULL,
                            jd_ids       JSONB NOT NULL,
                            custom_jd    TEXT,
                            notes        TEXT
                        );
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS eval_results (
                            id                UUID PRIMARY KEY,
                            run_id            UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
                            model             TEXT NOT NULL,
                            jd_id             TEXT NOT NULL,
                            status            TEXT NOT NULL,
                            error             TEXT,
                            duration_ms       INTEGER,
                            input_tokens      INTEGER,
                            output_tokens     INTEGER,
                            fallback_used     BOOLEAN NOT NULL DEFAULT FALSE,
                            schema_score      REAL,
                            schema_passed     BOOLEAN,
                            schema_errors     JSONB,
                            ats_score         REAL,
                            ats_coverage      REAL,
                            missing_keywords  JSONB,
                            judge_overall     REAL,
                            judge_relevance   REAL,
                            judge_quality     REAL,
                            judge_coherence   REAL,
                            judge_reasoning   TEXT,
                            composite_score   REAL,
                            resume_json       JSONB,
                            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        );
                    """)
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id);")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_eval_results_model ON eval_results(model);")
```

- [ ] **Step 4: Implement the accessors**

Add an `# Eval runs` section to `DBStorage`. Column order is fixed once and reused by every SELECT:

```python
    _EVAL_RESULT_COLUMNS = (
        "id", "run_id", "model", "jd_id", "status", "error", "duration_ms",
        "input_tokens", "output_tokens", "fallback_used", "schema_score",
        "schema_passed", "schema_errors", "ats_score", "ats_coverage",
        "missing_keywords", "judge_overall", "judge_relevance", "judge_quality",
        "judge_coherence", "judge_reasoning", "composite_score", "resume_json",
        "created_at",
    )

    _EVAL_RUN_COLUMNS = (
        "id", "created_at", "finished_at", "created_by", "status",
        "data_source", "judge_model", "models", "jd_ids", "custom_jd", "notes",
    )

    def _row_to_dict(self, columns, row):
        out = {}
        for name, value in zip(columns, row):
            if name in ("schema_errors", "missing_keywords", "resume_json", "models", "jd_ids"):
                value = self._coerce_json(value) if not isinstance(value, list) else value
            elif name in ("created_at", "finished_at") and value is not None:
                value = value.isoformat()
            elif name in ("id", "run_id") and value is not None:
                value = str(value)
            out[name] = value
        return out
```

Then the methods:

```python
    def create_eval_run(self, run_id: str, created_by: str, data_source: str,
                        judge_model: Optional[str], models: list, jd_ids: list,
                        custom_jd: Optional[str], notes: Optional[str]) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO eval_runs
                        (id, created_by, status, data_source, judge_model, models, jd_ids, custom_jd, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (run_id, created_by, "running", data_source, judge_model,
                     Json(list(models)), Json(list(jd_ids)), custom_jd, notes),
                )
        self.logger.info("Eval run %s created by %s", run_id, created_by)

    def finish_eval_run(self, run_id: str, status: str) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE eval_runs SET status = %s, finished_at = NOW() WHERE id = %s",
                    (status, run_id),
                )

    def insert_eval_result(self, result: Dict[str, Any]) -> None:
        columns = [c for c in self._EVAL_RESULT_COLUMNS if c != "created_at"]
        json_columns = {"schema_errors", "missing_keywords", "resume_json"}
        values = [
            Json(result.get(c)) if c in json_columns and result.get(c) is not None else result.get(c)
            for c in columns
        ]
        placeholders = ", ".join(["%s"] * len(columns))
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO eval_results ({', '.join(columns)}) VALUES ({placeholders})",
                    tuple(values),
                )

    def list_eval_runs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(self._EVAL_RUN_COLUMNS)} FROM eval_runs "
                    "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
                rows = cur.fetchall()
        return [self._row_to_dict(self._EVAL_RUN_COLUMNS, r) for r in rows]

    def get_eval_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(self._EVAL_RUN_COLUMNS)} FROM eval_runs WHERE id = %s",
                    (run_id,),
                )
                row = cur.fetchone()
        return self._row_to_dict(self._EVAL_RUN_COLUMNS, row) if row else None

    def get_eval_results(self, run_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(self._EVAL_RESULT_COLUMNS)} FROM eval_results "
                    "WHERE run_id = %s ORDER BY model, jd_id",
                    (run_id,),
                )
                rows = cur.fetchall()
        return [self._row_to_dict(self._EVAL_RESULT_COLUMNS, r) for r in rows]

    def get_eval_result(self, result_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {', '.join(self._EVAL_RESULT_COLUMNS)} FROM eval_results WHERE id = %s",
                    (result_id,),
                )
                row = cur.fetchone()
        return self._row_to_dict(self._EVAL_RESULT_COLUMNS, row) if row else None

    def mark_running_evals_interrupted(self) -> int:
        """A container restart leaves 'running' rows behind; close them out."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE eval_runs SET status = 'interrupted', finished_at = NOW() WHERE status = 'running'"
                )
                return cur.rowcount or 0
```

and the aggregate:

```python
    def get_eval_model_comparison(self) -> List[Dict[str, Any]]:
        """Per-model aggregate across every stored eval result."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT model,
                           COUNT(DISTINCT run_id)                                    AS runs,
                           COUNT(*)                                                  AS cells,
                           AVG(CASE WHEN status = 'success' THEN 1.0 ELSE 0.0 END)   AS success_rate,
                           AVG(composite_score)                                      AS avg_composite,
                           AVG(schema_score)                                         AS avg_schema,
                           AVG(ats_score)                                            AS avg_ats,
                           AVG(judge_overall)                                        AS avg_judge,
                           AVG(duration_ms)                                          AS avg_duration_ms,
                           MAX(created_at)                                           AS last_run_at
                    FROM eval_results
                    GROUP BY model
                    ORDER BY AVG(composite_score) DESC NULLS LAST
                    """
                )
                rows = cur.fetchall()
        def _f(v):
            return round(float(v), 4) if v is not None else None
        return [
            {
                "model": r[0], "runs": int(r[1]), "cells": int(r[2]),
                "success_rate": _f(r[3]), "avg_composite": _f(r[4]),
                "avg_schema": _f(r[5]), "avg_ats": _f(r[6]), "avg_judge": _f(r[7]),
                "avg_duration_ms": int(r[8]) if r[8] is not None else None,
                "last_run_at": r[9].isoformat() if r[9] else None,
            }
            for r in rows
        ]
```

`mark_running_evals_interrupted` runs `UPDATE eval_runs SET status = 'interrupted', finished_at = NOW() WHERE status = 'running'` and returns `cur.rowcount`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_eval_storage.py -v`
Expected: 5 passed

- [ ] **Step 6: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/utils/db_storage.py backend/tests/unit/test_eval_storage.py
git commit -m "feat(db): persist eval runs and per-cell results"
```

---

### Task 10: `evals/runner.py` — the shared eval runner

**Files:**
- Create: `backend/evals/runner.py`
- Modify: `backend/tests/integration/test_multi_model.py` (become a wrapper)
- Test: `backend/tests/unit/test_eval_runner.py` (create)

**Interfaces:**
- Consumes: `evals.fixtures` (Task 8), `evals.evaluators` (Task 8), `DBStorage` eval accessors (Task 9), `Bot` (Task 4)
- Produces:
  - `MAX_MODELS = 5`, `MAX_CELLS = 20`, `CONCURRENCY = 3`
  - `class EvalSpecError(ValueError)`
  - `@dataclass EvalSpec(models: List[str], jd_ids: List[str], custom_jd: Optional[str], data_source: str, judge_model: Optional[str], created_by: str, notes: Optional[str] = None)` with `cells() -> List[Tuple[str, str]]` and `jd_text(jd_id) -> str`
  - `def validate_spec(spec: EvalSpec) -> None`
  - `async def run_eval(spec: EvalSpec, *, db=None, on_cell=None, run_id: Optional[str] = None) -> str` — returns the run id (minted here when not supplied, so the API can hand the id to the client before the run starts); `on_cell` is an async callable taking the persisted result dict

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_eval_runner.py`:

```python
"""Tests for the shared eval runner. No real models, no real database."""

from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel

from evals import runner
from evals.runner import EvalSpec, EvalSpecError


class RecordingDB:
    """Captures what the runner would persist."""

    def __init__(self):
        self.runs = []
        self.results = []
        self.finished = []

    def create_eval_run(self, **kwargs):
        self.runs.append(kwargs)

    def insert_eval_result(self, result):
        self.results.append(result)

    def finish_eval_run(self, run_id, status):
        self.finished.append((run_id, status))


def _spec(**overrides):
    base = dict(
        models=["test:a", "test:b"],
        jd_ids=["senior_swe"],
        custom_jd=None,
        data_source="fixture",
        judge_model="test:judge",
        created_by="admin@example.com",
    )
    base.update(overrides)
    return EvalSpec(**base)


# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------

def test_rejects_empty_models():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(models=[]))


def test_rejects_too_many_models():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(models=[f"test:{i}" for i in range(runner.MAX_MODELS + 1)]))


def test_rejects_unknown_fixture_id():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(jd_ids=["not_a_fixture"]))


def test_rejects_both_fixtures_and_custom_jd():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(jd_ids=["senior_swe"], custom_jd="Some pasted JD"))


def test_rejects_no_job_description_at_all():
    with pytest.raises(EvalSpecError):
        runner.validate_spec(_spec(jd_ids=[], custom_jd=None))


def test_accepts_custom_jd_alone():
    runner.validate_spec(_spec(jd_ids=[], custom_jd="Senior Python engineer wanted"))


def test_cells_are_model_x_jd():
    spec = _spec(models=["test:a", "test:b"], jd_ids=["senior_swe", "junior_analyst"])
    assert len(spec.cells()) == 4


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

async def test_run_persists_one_result_per_cell(sample_resume_output):
    db = RecordingDB()
    seen = []

    async def on_cell(result):
        seen.append(result)

    with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
            custom_output_args=sample_resume_output.model_dump())), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        run_id = await runner.run_eval(_spec(models=["test:a", "test:b"]), db=db, on_cell=on_cell)

    assert len(db.results) == 2
    assert len(seen) == 2
    assert db.finished == [(run_id, "complete")]
    assert all(r["status"] == "success" for r in db.results)
    assert db.results[0]["resume_json"]["language"] == "en"
    assert db.results[0]["composite_score"] is not None


async def test_failing_cell_is_recorded_and_does_not_abort_run(sample_resume_output):
    db = RecordingDB()

    def model_for(name):
        if name == "test:bad":
            raise RuntimeError("provider exploded")
        return TestModel(custom_output_args=sample_resume_output.model_dump())

    with patch.object(runner, "_model_for", side_effect=model_for), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        run_id = await runner.run_eval(_spec(models=["test:bad", "test:good"]), db=db)

    by_model = {r["model"]: r for r in db.results}
    assert by_model["test:bad"]["status"] == "error"
    assert "provider exploded" in by_model["test:bad"]["error"]
    assert by_model["test:good"]["status"] == "success"
    assert db.finished == [(run_id, "complete")]


async def test_cell_cap_is_enforced():
    spec = _spec(models=[f"test:{i}" for i in range(5)], jd_ids=["senior_swe", "junior_analyst", "product_manager"])
    with patch.object(runner, "MAX_CELLS", 10):
        with pytest.raises(EvalSpecError, match="cells"):
            runner.validate_spec(spec)


async def test_custom_jd_is_used_and_labelled(sample_resume_output):
    db = RecordingDB()
    with patch.object(runner, "_model_for", side_effect=lambda name: TestModel(
            custom_output_args=sample_resume_output.model_dump())), \
         patch.object(runner, "_judge_for", side_effect=lambda name: TestModel(
            custom_output_args={"relevance": 8, "quality": 8, "coherence": 8, "reasoning": "ok"})):
        await runner.run_eval(_spec(models=["test:a"], jd_ids=[], custom_jd="Pasted JD text"), db=db)

    assert db.results[0]["jd_id"] == "custom"
    assert db.runs[0]["custom_jd"] == "Pasted JD text"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_eval_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.runner'`

- [ ] **Step 3: Implement the runner**

Create `backend/evals/runner.py`:

```python
"""Shared evaluation runner.

One implementation, two callers: the pytest multi-model integration test and
the admin dashboard's eval endpoint. Each (model, job description) pair is one
cell: generate a resume with that model, score it, persist the row.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from evals.evaluators.ats_evaluator import ATSEvaluator
from evals.evaluators.llm_judge import LLMJudge
from evals.evaluators.schema_evaluator import SchemaEvaluator
from evals.fixtures import CUSTOM_JD_ID, JD_FIXTURES, StubVectorStore

logger = logging.getLogger("betterresume.evals.runner")

MAX_MODELS = 5
MAX_CELLS = 20
CONCURRENCY = 3
DATA_SOURCE_FIXTURE = "fixture"


class EvalSpecError(ValueError):
    """The requested evaluation is not runnable."""


@dataclass
class EvalSpec:
    models: List[str]
    jd_ids: List[str]
    custom_jd: Optional[str]
    data_source: str
    judge_model: Optional[str]
    created_by: str
    notes: Optional[str] = None

    def jd_entries(self) -> List[Tuple[str, str]]:
        """[(jd_id, jd_text)] for this spec."""
        if self.custom_jd:
            return [(CUSTOM_JD_ID, self.custom_jd)]
        return [(jd_id, JD_FIXTURES[jd_id].text) for jd_id in self.jd_ids]

    def cells(self) -> List[Tuple[str, str]]:
        """[(model, jd_id)] for this spec."""
        return [(model, jd_id) for model in self.models for jd_id, _ in self.jd_entries()]


def validate_spec(spec: EvalSpec) -> None:
    if not spec.models:
        raise EvalSpecError("Select at least one model")
    if len(spec.models) > MAX_MODELS:
        raise EvalSpecError(f"At most {MAX_MODELS} models per run")
    if spec.custom_jd and spec.jd_ids:
        raise EvalSpecError("Provide either fixture job descriptions or a custom one, not both")
    if not spec.custom_jd and not spec.jd_ids:
        raise EvalSpecError("Select at least one job description")
    unknown = [j for j in spec.jd_ids if j not in JD_FIXTURES]
    if unknown:
        raise EvalSpecError(f"Unknown job description fixture(s): {', '.join(unknown)}")
    if len(spec.cells()) > MAX_CELLS:
        raise EvalSpecError(f"That is {len(spec.cells())} cells; the limit is {MAX_CELLS} per run")
    if spec.data_source != DATA_SOURCE_FIXTURE and not spec.data_source.startswith("user:"):
        raise EvalSpecError("data_source must be 'fixture' or 'user:<user_id>'")


def _model_for(model_string: str):
    """Indirection so tests can substitute TestModel without touching the runner."""
    return model_string


def _judge_for(model_string: Optional[str]):
    """Indirection so tests can substitute the judge model."""
    return model_string


def _vector_store_for(spec: EvalSpec):
    if spec.data_source == DATA_SOURCE_FIXTURE:
        return StubVectorStore(user_id="eval_fixture_user"), "eval_fixture_user"
    user_id = spec.data_source.split(":", 1)[1]
    from llm.vector_store import PGVectorStore

    return PGVectorStore(user_id=user_id), user_id


async def _run_cell(spec: EvalSpec, model_string: str, jd_id: str, jd_text: str, run_id: str) -> dict:
    """Generate + score one (model, JD) pair. Never raises; failures are recorded."""
    from bot import Bot

    result: dict = {
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "model": model_string,
        "jd_id": jd_id,
        "status": "error",
        "error": None,
        "duration_ms": None,
        "input_tokens": None,
        "output_tokens": None,
        "fallback_used": False,
        "schema_score": None, "schema_passed": None, "schema_errors": None,
        "ats_score": None, "ats_coverage": None, "missing_keywords": None,
        "judge_overall": None, "judge_relevance": None, "judge_quality": None,
        "judge_coherence": None, "judge_reasoning": None,
        "composite_score": None, "resume_json": None,
    }
    start = time.monotonic()
    try:
        store, user_id = _vector_store_for(spec)
        bot = Bot(
            user_id=user_id,
            vector_store=store,
            model=_model_for(model_string),
            auto_ingest=False,
        )
        resume = await bot.generate_resume(jd_text)
        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        result["fallback_used"] = bool(bot.last_fallback_used)
        result["resume_json"] = resume.model_dump()

        schema = SchemaEvaluator().evaluate(resume)
        result.update(
            schema_score=schema.score,
            schema_passed=schema.passed,
            schema_errors=list(schema.errors or []),
        )

        ats = ATSEvaluator().evaluate(resume, jd_text)
        result.update(
            ats_score=ats.score,
            ats_coverage=ats.keyword_coverage,
            missing_keywords=list(ats.missing_keywords or [])[:20],
        )

        judge_result = None
        if spec.judge_model:
            judge_result = await LLMJudge(judge_model=_judge_for(spec.judge_model)).aevaluate(resume, jd_text)
            result.update(
                judge_overall=judge_result.overall_score,
                judge_relevance=judge_result.relevance_score,
                judge_quality=judge_result.quality_score,
                judge_coherence=judge_result.coherence_score,
                judge_reasoning=judge_result.reasoning,
            )

        result["composite_score"] = _composite(schema.score, ats.score,
                                               judge_result.overall_score if judge_result else None)
        result["status"] = "success"
    except Exception as exc:
        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        result["error"] = f"{type(exc).__name__}: {exc}"[:2000]
        logger.warning("Eval cell failed model=%s jd=%s: %s", model_string, jd_id, exc)
    return result


def _composite(schema_score: float, ats_score: float, judge_score: Optional[float]) -> float:
    """Same weighting as ResumeEvaluationReport.composite_score."""
    if judge_score is not None:
        return round(0.40 * schema_score + 0.35 * ats_score + 0.25 * judge_score, 3)
    return round(0.53 * schema_score + 0.47 * ats_score, 3)


async def run_eval(
    spec: EvalSpec,
    *,
    db: Any = None,
    on_cell: Optional[Callable[[dict], Awaitable[None]]] = None,
    run_id: Optional[str] = None,
) -> str:
    """Execute an evaluation run, persisting each cell as it completes.

    Returns the run id. Callers that need the id before the run starts (the API,
    so it can hand the client a stream to follow) pass one in. Cell failures are
    recorded, not raised.
    """
    validate_spec(spec)
    if db is None:
        from utils.db_storage import DBStorage
        db = DBStorage()

    run_id = run_id or str(uuid.uuid4())
    db.create_eval_run(
        run_id=run_id,
        created_by=spec.created_by,
        data_source=spec.data_source,
        judge_model=spec.judge_model,
        models=list(spec.models),
        jd_ids=[jd_id for jd_id, _ in spec.jd_entries()],
        custom_jd=spec.custom_jd,
        notes=spec.notes,
    )
    logger.info("Eval run %s started by %s: %d cells", run_id, spec.created_by, len(spec.cells()))

    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _guarded(model_string: str, jd_id: str, jd_text: str):
        async with semaphore:
            result = await _run_cell(spec, model_string, jd_id, jd_text, run_id)
        db.insert_eval_result(result)
        if on_cell:
            await on_cell(result)
        return result

    tasks = [
        _guarded(model_string, jd_id, jd_text)
        for model_string in spec.models
        for jd_id, jd_text in spec.jd_entries()
    ]
    try:
        await asyncio.gather(*tasks)
        db.finish_eval_run(run_id, "complete")
    except Exception:
        logger.exception("Eval run %s failed", run_id)
        db.finish_eval_run(run_id, "failed")
        raise
    logger.info("Eval run %s complete", run_id)
    return run_id
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_eval_runner.py -v`
Expected: 11 passed

- [ ] **Step 5: Rewrite the integration test as a wrapper**

Replace the body of `backend/tests/integration/test_multi_model.py`:

```python
"""
Multi-model comparison test.

Run with:
    pytest tests/integration/test_multi_model.py -v --real-ai \\
      --models "google-gla:gemini-2.5-flash-lite,openai:gpt-4o-mini"

Thin wrapper over evals.runner so the CLI and the admin dashboard measure
exactly the same thing.
"""
import os

import pytest

from evals.runner import EvalSpec, run_eval

pytestmark = pytest.mark.timeout(600)


class _CollectingDB:
    def __init__(self):
        self.results = []

    def create_eval_run(self, **kwargs):
        pass

    def insert_eval_result(self, result):
        self.results.append(result)

    def finish_eval_run(self, run_id, status):
        pass


@pytest.mark.real_ai
@pytest.mark.slow
async def test_multi_model_comparison(models_under_test):
    """Generate a resume with each model in --models, score it, print a ranked
    table. Hard assertion: every model must produce a schema-valid resume."""
    db = _CollectingDB()
    spec = EvalSpec(
        models=models_under_test,
        jd_ids=["senior_swe"],
        custom_jd=None,
        data_source="fixture",
        judge_model=os.getenv("JUDGE_MODEL", "google-gla:gemini-2.5-flash-lite"),
        created_by="pytest",
    )
    await run_eval(spec, db=db)

    for r in sorted(db.results, key=lambda x: x["composite_score"] or 0, reverse=True):
        print(f"{r['model']:<48} schema={r['schema_score']} ats={r['ats_score']} "
              f"judge={r['judge_overall']} composite={r['composite_score']} status={r['status']}")

    failed = [r["model"] for r in db.results if not r["schema_passed"]]
    assert not failed, f"These models produced schema-invalid resumes: {failed}"
```

- [ ] **Step 6: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/evals/runner.py backend/tests/unit/test_eval_runner.py backend/tests/integration/test_multi_model.py
git commit -m "feat(evals): add shared eval runner used by pytest and the API"
```

---

### Task 11: Admin endpoints — model config and catalog

**Files:**
- Modify: `backend/api/routers/admin.py`
- Test: `backend/tests/unit/test_admin_models_api.py` (create)

**Interfaces:**
- Consumes: `llm.model_config` (Task 2), `llm.openrouter_catalog` (Task 7), `DBStorage.get_app_settings_meta` (Task 1)
- Produces:
  - `GET /admin/models?tools_only=true&q=` → `{"models": [CatalogModel.as_dict(), ...]}`; 503 `{"detail": "..."}` when the feed is unreachable
  - `GET /admin/model-config` → `{"tasks": {"generation": {"primary","fallback","updated_at","updated_by"}, ...}}`
  - `PUT /admin/model-config` body `{"task": "generation", "primary": "...", "fallback": "..." | null}` → the same shape as GET; 400 on validation failure

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_admin_models_api.py`:

```python
"""Tests for the admin model-catalog and model-config endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import require_admin
from api.routers import admin as admin_router
from llm import model_config
from llm.openrouter_catalog import CatalogModel, CatalogUnavailable

CATALOG = [
    CatalogModel("a/tool-model", "openrouter:a/tool-model", "Tool Model", 128000, 0.2, 0.8, True, True),
    CatalogModel("b/plain-model", "openrouter:b/plain-model", "Plain Model", 32000, 0.1, 0.3, False, False),
]


def _client():
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[require_admin] = lambda: {"email": "daltioan@gmail.com"}
    return TestClient(app)


def test_models_requires_auth():
    app = FastAPI()
    app.include_router(admin_router.router)
    assert TestClient(app).get("/admin/models").status_code == 401


def test_models_defaults_to_tool_capable_only():
    with patch("api.routers.admin.fetch_models", AsyncMock(return_value=CATALOG)):
        resp = _client().get("/admin/models")
    ids = [m["id"] for m in resp.json()["models"]]
    assert ids == ["a/tool-model"]


def test_models_show_all_includes_non_tool_models():
    with patch("api.routers.admin.fetch_models", AsyncMock(return_value=CATALOG)):
        resp = _client().get("/admin/models?tools_only=false")
    assert len(resp.json()["models"]) == 2


def test_models_search_filters_by_id_and_name():
    with patch("api.routers.admin.fetch_models", AsyncMock(return_value=CATALOG)):
        resp = _client().get("/admin/models?tools_only=false&q=plain")
    assert [m["id"] for m in resp.json()["models"]] == ["b/plain-model"]


def test_models_503_when_feed_unavailable():
    with patch("api.routers.admin.fetch_models", AsyncMock(side_effect=CatalogUnavailable("down"))):
        resp = _client().get("/admin/models")
    assert resp.status_code == 503


def test_get_model_config_returns_all_tasks():
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:g", "google-gla:f"),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
    )
    with patch("api.routers.admin.get_model_config", return_value=cfg), \
         patch("api.routers.admin.DBStorage.get_app_settings_meta", return_value={}):
        body = _client().get("/admin/model-config").json()
    assert body["tasks"]["generation"]["primary"] == "openrouter:g"
    assert body["tasks"]["generation"]["fallback"] == "google-gla:f"
    assert set(body["tasks"]) == {"generation", "translation", "import"}


def test_put_model_config_persists_and_returns_new_state():
    cfg = model_config.ModelConfig(
        generation=model_config.TaskModels("openrouter:new", None),
        translation=model_config.TaskModels("openrouter:t", None),
        import_=model_config.TaskModels("openrouter:i", None),
    )
    with patch("api.routers.admin.set_task_models") as setter, \
         patch("api.routers.admin.get_model_config", return_value=cfg), \
         patch("api.routers.admin.DBStorage.get_app_settings_meta", return_value={}):
        resp = _client().put("/admin/model-config", json={
            "task": "generation", "primary": "openrouter:new", "fallback": None,
        })
    assert resp.status_code == 200
    setter.assert_called_once_with("generation", "openrouter:new", None, updated_by="daltioan@gmail.com")
    assert resp.json()["tasks"]["generation"]["primary"] == "openrouter:new"


def test_put_model_config_400_on_invalid_model_string():
    with patch("api.routers.admin.set_task_models", side_effect=ValueError("must be provider-prefixed")):
        resp = _client().put("/admin/model-config", json={
            "task": "generation", "primary": "no-provider", "fallback": None,
        })
    assert resp.status_code == 400
    assert "provider-prefixed" in resp.json()["detail"]


def test_put_model_config_422_on_unknown_task():
    resp = _client().put("/admin/model-config", json={
        "task": "nonsense", "primary": "openrouter:x", "fallback": None,
    })
    assert resp.status_code == 422
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_admin_models_api.py -v`
Expected: FAIL — 404s, because the routes do not exist

- [ ] **Step 3: Implement**

Add to `backend/api/routers/admin.py`:

```python
from typing import Literal, Optional

from pydantic import BaseModel

from llm.model_config import TASKS, get_model_config, set_task_models
from llm.openrouter_catalog import CatalogUnavailable, fetch_models


class ModelConfigUpdate(BaseModel):
    task: Literal["generation", "translation", "import"]
    primary: str
    fallback: Optional[str] = None


def _model_config_payload() -> dict:
    config = get_model_config(force_refresh=True)
    meta = DBStorage().get_app_settings_meta("model.")
    tasks = {}
    for task in TASKS:
        task_models = config.for_task(task)
        row = meta.get(f"model.{task}", {})
        tasks[task] = {
            "primary": task_models.primary,
            "fallback": task_models.fallback,
            "updated_at": row.get("updated_at"),
            "updated_by": row.get("updated_by"),
        }
    return {"tasks": tasks}


@router.get("/models")
async def list_models(tools_only: bool = True, q: str = "", claims: dict = Depends(require_admin)):
    """OpenRouter's model catalog, filtered for the admin picker."""
    try:
        models = await fetch_models()
    except CatalogUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"OpenRouter model list unavailable: {exc}")
    if tools_only:
        models = [m for m in models if m.supports_tools]
    if q:
        needle = q.lower()
        models = [m for m in models if needle in m.id.lower() or needle in m.name.lower()]
    return {"models": [m.as_dict() for m in models]}


@router.get("/model-config")
async def read_model_config(claims: dict = Depends(require_admin)):
    """Current per-task model settings."""
    return _model_config_payload()


@router.put("/model-config")
async def update_model_config(update: ModelConfigUpdate, claims: dict = Depends(require_admin)):
    """Set the primary/fallback models for one task."""
    try:
        set_task_models(update.task, update.primary, update.fallback, updated_by=claims.get("email"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info("Model config for %s changed by %s", update.task, claims.get("email"))
    return _model_config_payload()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_admin_models_api.py -v`
Expected: 9 passed

- [ ] **Step 5: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/api/routers/admin.py backend/tests/unit/test_admin_models_api.py
git commit -m "feat(admin): add model catalog and model-config endpoints"
```

---

### Task 12: Admin endpoints — eval runs

**Files:**
- Modify: `backend/api/routers/admin.py`
- Modify: `backend/api/main.py` (startup sweep)
- Test: `backend/tests/unit/test_admin_evals_api.py` (create)

**Interfaces:**
- Consumes: `evals.runner` (Task 10), `evals.fixtures.list_fixtures` (Task 8), eval storage (Task 9), `_make_writer` pattern from `api/routers/resume.py`
- Produces:
  - `GET /admin/evals/fixtures` → `{"job_descriptions": [...], "default_judge_model": "..."}`
  - `POST /admin/evals` body `{models, jd_ids, custom_jd, data_source, judge_model, notes}` → `{"run_id": "..."}` (202); 400 on `EvalSpecError`
  - `GET /admin/evals` → `{"runs": [...]}`
  - `GET /admin/evals/{run_id}` → `{"run": {...}, "results": [...]}`; 404 when absent
  - `GET /admin/evals/{run_id}/stream` → SSE, `event: cell` per result then `event: done`
  - `GET /admin/evals/compare` → `{"models": [...]}`
  - `GET /admin/evals/results/{result_id}/download?format=word|latex` → file response

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_admin_evals_api.py`:

```python
"""Tests for the admin eval endpoints."""

from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import require_admin
from api.routers import admin as admin_router
from evals.runner import EvalSpecError
from utils.db_storage import DBStorage

RUN = {
    "id": "11111111-1111-1111-1111-111111111111",
    "created_at": "2026-08-10T12:00:00+00:00",
    "finished_at": None,
    "created_by": "daltioan@gmail.com",
    "status": "complete",
    "data_source": "fixture",
    "judge_model": "google-gla:gemini-2.5-flash-lite",
    "models": ["openrouter:a"],
    "jd_ids": ["senior_swe"],
    "custom_jd": None,
    "notes": None,
}

RESULT = {
    "id": "22222222-2222-2222-2222-222222222222",
    "run_id": RUN["id"],
    "model": "openrouter:a",
    "jd_id": "senior_swe",
    "status": "success",
    "composite_score": 0.87,
    "resume_json": {"language": "en"},
}


def _client():
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[require_admin] = lambda: {"email": "daltioan@gmail.com"}
    return TestClient(app)


def test_evals_require_auth():
    app = FastAPI()
    app.include_router(admin_router.router)
    assert TestClient(app).get("/admin/evals").status_code == 401


def test_fixtures_lists_job_descriptions():
    body = _client().get("/admin/evals/fixtures").json()
    ids = [jd["id"] for jd in body["job_descriptions"]]
    assert "senior_swe" in ids
    assert body["default_judge_model"]


def test_start_run_returns_run_id():
    with patch("api.routers.admin.run_eval", AsyncMock(return_value=RUN["id"])):
        resp = _client().post("/admin/evals", json={
            "models": ["openrouter:a"], "jd_ids": ["senior_swe"],
            "custom_jd": None, "data_source": "fixture",
            "judge_model": "google-gla:gemini-2.5-flash-lite", "notes": None,
        })
    assert resp.status_code == 202
    assert resp.json()["run_id"] == RUN["id"]


def test_start_run_400_on_invalid_spec():
    with patch("api.routers.admin.validate_spec", side_effect=EvalSpecError("At most 5 models per run")):
        resp = _client().post("/admin/evals", json={
            "models": ["a:1", "b:2", "c:3", "d:4", "e:5", "f:6"], "jd_ids": ["senior_swe"],
            "custom_jd": None, "data_source": "fixture", "judge_model": None, "notes": None,
        })
    assert resp.status_code == 400
    assert "At most 5 models" in resp.json()["detail"]


def test_list_runs():
    with patch.object(DBStorage, "list_eval_runs", return_value=[RUN]):
        body = _client().get("/admin/evals").json()
    assert body["runs"][0]["id"] == RUN["id"]


def test_get_run_returns_run_and_results():
    with patch.object(DBStorage, "get_eval_run", return_value=RUN), \
         patch.object(DBStorage, "get_eval_results", return_value=[RESULT]):
        body = _client().get(f"/admin/evals/{RUN['id']}").json()
    assert body["run"]["status"] == "complete"
    assert body["results"][0]["composite_score"] == 0.87


def test_get_run_404_when_missing():
    with patch.object(DBStorage, "get_eval_run", return_value=None):
        resp = _client().get(f"/admin/evals/{RUN['id']}")
    assert resp.status_code == 404


def test_compare_returns_per_model_aggregates():
    rows = [{"model": "openrouter:a", "runs": 2, "cells": 4, "avg_composite": 0.81}]
    with patch.object(DBStorage, "get_eval_model_comparison", return_value=rows):
        body = _client().get("/admin/evals/compare").json()
    assert body["models"][0]["avg_composite"] == 0.81


def test_download_404_when_result_missing():
    with patch.object(DBStorage, "get_eval_result", return_value=None):
        resp = _client().get(f"/admin/evals/results/{RESULT['id']}/download?format=word")
    assert resp.status_code == 404


def test_download_400_when_result_has_no_resume():
    with patch.object(DBStorage, "get_eval_result", return_value={**RESULT, "resume_json": None}):
        resp = _client().get(f"/admin/evals/results/{RESULT['id']}/download?format=word")
    assert resp.status_code == 400
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/unit/test_admin_evals_api.py -v`
Expected: FAIL — 404s for the missing routes

- [ ] **Step 3: Implement the endpoints**

Add to `backend/api/routers/admin.py`:

```python
import asyncio
import os
import tempfile
from typing import Any, Dict, List

from fastapi.responses import FileResponse, StreamingResponse

from evals.fixtures import list_fixtures
from evals.runner import EvalSpec, EvalSpecError, run_eval, validate_spec
from models.resume import ResumeOutputFormat

DEFAULT_JUDGE_MODEL = os.getenv("JUDGE_MODEL", "google-gla:gemini-2.5-flash-lite")

# Live cell queues for in-flight runs, keyed by run_id, so /stream can follow a
# run started by POST /evals. Dropped when the run finishes; history endpoints
# serve anything older.
_EVAL_STREAMS: Dict[str, "asyncio.Queue[dict]"] = {}


class EvalRunRequest(BaseModel):
    models: List[str]
    jd_ids: List[str] = []
    custom_jd: Optional[str] = None
    data_source: str = "fixture"
    judge_model: Optional[str] = DEFAULT_JUDGE_MODEL
    notes: Optional[str] = None


@router.get("/evals/fixtures")
async def eval_fixtures(claims: dict = Depends(require_admin)):
    """Job-description fixtures available for evaluation runs."""
    return {"job_descriptions": list_fixtures(), "default_judge_model": DEFAULT_JUDGE_MODEL}


@router.post("/evals", status_code=202)
async def start_eval(req: EvalRunRequest, claims: dict = Depends(require_admin)):
    """Start an evaluation run in the background; returns its id immediately."""
    spec = EvalSpec(
        models=req.models,
        jd_ids=req.jd_ids,
        custom_jd=req.custom_jd,
        data_source=req.data_source,
        judge_model=req.judge_model,
        created_by=claims.get("email") or "admin",
        notes=req.notes,
    )
    try:
        validate_spec(spec)
    except EvalSpecError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Mint the id here so the client can start streaming before the run does.
    run_id = str(uuid.uuid4())
    queue: "asyncio.Queue[dict]" = asyncio.Queue()
    _EVAL_STREAMS[run_id] = queue

    async def _on_cell(result: dict):
        await queue.put(result)

    async def _run():
        try:
            await run_eval(spec, on_cell=_on_cell, run_id=run_id)
        except Exception:
            logger.exception("Eval run %s failed", run_id)
        finally:
            await queue.put({"_done": True})

    asyncio.create_task(_run())
    logger.info("Eval run %s requested by %s: %d model(s)", run_id, claims.get("email"), len(req.models))
    return {"run_id": run_id}


@router.get("/evals")
async def list_evals(limit: int = Query(default=50, ge=1, le=200), claims: dict = Depends(require_admin)):
    """Past evaluation runs, newest first."""
    return {"runs": DBStorage().list_eval_runs(limit=limit)}


@router.get("/evals/compare")
async def compare_evals(claims: dict = Depends(require_admin)):
    """Per-model aggregate across every stored eval result."""
    return {"models": DBStorage().get_eval_model_comparison()}


@router.get("/evals/{run_id}")
async def get_eval(run_id: str, claims: dict = Depends(require_admin)):
    """One run with all of its cells."""
    db = DBStorage()
    run = db.get_eval_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return {"run": run, "results": db.get_eval_results(run_id)}


@router.get("/evals/{run_id}/stream")
async def stream_eval(run_id: str, claims: dict = Depends(require_admin)):
    """SSE stream of cells for an in-flight run."""
    queue = _EVAL_STREAMS.get(run_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="No in-flight run with that id")

    async def _events():
        try:
            while True:
                item = await queue.get()
                if item.get("_done"):
                    yield sse_event("done", {})
                    return
                yield sse_event("cell", item)
        finally:
            _EVAL_STREAMS.pop(run_id, None)

    return StreamingResponse(_events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/evals/results/{result_id}/download")
async def download_eval_resume(result_id: str, format: str = "word", claims: dict = Depends(require_admin)):
    """Render a stored eval resume through the production writers."""
    result = DBStorage().get_eval_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Eval result not found")
    if not result.get("resume_json"):
        raise HTTPException(status_code=400, detail="This result has no generated resume")

    resume = ResumeOutputFormat.model_validate(result["resume_json"])
    writer = _make_writer(format.lower(), csv_path=None, profile_path=None, profile=None)
    out_dir = tempfile.mkdtemp(prefix="eval_resume_")
    output = os.path.join(out_dir, f"eval_{result_id}{writer.file_ending}")
    try:
        writer.write(resume, output=output, to_pdf=True)
    except Exception:
        logger.exception("Failed rendering eval resume %s", result_id)
        raise HTTPException(status_code=500, detail="Failed to render resume")
    return FileResponse(output, filename=os.path.basename(output))
```

`sse_event`, `SSE_HEADERS` and `_make_writer` live in `api/routers/resume.py` / `api/utils.py`. Import `sse_event` from `api.utils`, and move `SSE_HEADERS` and `_make_writer` out of `api/routers/resume.py` into `api/utils.py` so both routers share one definition rather than duplicating it — update `resume.py` to import them from their new home. Confirm `_make_writer` tolerates `csv_path=None`; if the writers require a CSV path, pass the eval fixture CSV path instead and note it in the docstring. `run_eval` already accepts `run_id` (Task 10), so no runner change is needed here.

- [ ] **Step 4: Add the startup sweep**

In `backend/api/main.py` `lifespan`, after `DBStorage().init_schema()`:

```python
    try:
        interrupted = DBStorage().mark_running_evals_interrupted()
        if interrupted:
            logger.warning("Marked %d orphaned eval run(s) as interrupted", interrupted)
    except Exception as e:
        logger.error("Could not sweep orphaned eval runs: %s", e)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/unit/test_admin_evals_api.py -v`
Expected: 10 passed

- [ ] **Step 6: Run the full suite and commit**

```bash
cd backend && pytest -q
git add backend/api/routers/admin.py backend/api/routers/resume.py backend/api/utils.py backend/api/main.py backend/evals/runner.py backend/tests/unit/test_admin_evals_api.py
git commit -m "feat(admin): add eval run endpoints with SSE progress and resume download"
```

---

### Task 13: Phase 2 documentation

**Files:**
- Modify: `backend/CLAUDE.md`, `CLAUDE.md` (root)

- [ ] **Step 1: Document the eval package and endpoints**

In `backend/CLAUDE.md`, add an `### Evaluation (`evals/`)` section describing `fixtures.py`, `evaluators/`, and `runner.py` (`run_eval`, caps `MAX_MODELS=5` / `MAX_CELLS=20` / `CONCURRENCY=3`), and note that `tests/integration/test_multi_model.py` is a wrapper over it. Extend the Admin section with the new endpoint table from the spec. Note `llm/openrouter_catalog.py` under the LLM layer.

- [ ] **Step 2: Update the root `CLAUDE.md`** with the same, briefly, under "Key subsystems".

- [ ] **Step 3: Commit**

```bash
git add backend/CLAUDE.md CLAUDE.md
git commit -m "docs: document the evals package and admin eval endpoints"
```

**Phase 2 is deployable here.** Verify manually: `curl -H "Authorization: Bearer $TOKEN" localhost:8000/resume/admin/models | head` returns tool-capable models.

---

# PHASE 3 — Dashboard

---

### Task 14: Frontend API client

**Files:**
- Modify: `frontend/src/services/api.ts`
- Test: `frontend/src/services/__tests__/adminApi.test.ts` (create)

**Interfaces:**
- Consumes: the Phase 2 endpoints
- Produces (all take `idToken` first, all throw `Error('forbidden')` on 401/403, matching `fetchAdminStats`):
  - `interface CatalogModel { id; model_string; name; context_length; prompt_price; completion_price; supports_tools; supports_structured_outputs }`
  - `interface TaskModelConfig { primary: string; fallback: string | null; updated_at: string | null; updated_by: string | null }`
  - `type ModelTask = 'generation' | 'translation' | 'import'`
  - `interface ModelConfigResponse { tasks: Record<ModelTask, TaskModelConfig> }`
  - `interface ModelComparisonRow { model: string; runs: number; cells: number; success_rate: number | null; avg_composite: number | null; avg_schema: number | null; avg_ats: number | null; avg_judge: number | null; avg_duration_ms: number | null; last_run_at: string | null }`
  - `interface EvalRun { id; created_at; finished_at; created_by; status; data_source; judge_model; models; jd_ids; custom_jd; notes }`
  - `interface EvalResult { id; run_id; model; jd_id; status; error; duration_ms; input_tokens; output_tokens; fallback_used; schema_score; schema_passed; ats_score; ats_coverage; missing_keywords; judge_overall; judge_reasoning; composite_score; resume_json }`
  - `fetchOpenRouterModels(idToken, opts?: {toolsOnly?: boolean; q?: string}): Promise<CatalogModel[]>`
  - `fetchModelConfig(idToken): Promise<ModelConfigResponse>`
  - `updateModelConfig(idToken, task, primary, fallback): Promise<ModelConfigResponse>`
  - `fetchEvalFixtures(idToken): Promise<{ job_descriptions: Array<{id;label;preview}>; default_judge_model: string }>`
  - `startEvalRun(idToken, payload): Promise<{ run_id: string }>`
  - `streamEvalRun(idToken, runId, onCell: (r: EvalResult) => void): Promise<void>`
  - `fetchEvalRuns(idToken): Promise<EvalRun[]>`
  - `fetchEvalRun(idToken, runId): Promise<{ run: EvalRun; results: EvalResult[] }>`
  - `fetchEvalComparison(idToken): Promise<ModelComparisonRow[]>`
  - `downloadEvalResume(idToken, resultId, format): Promise<Blob>`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/services/__tests__/adminApi.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  fetchOpenRouterModels,
  fetchModelConfig,
  updateModelConfig,
  startEvalRun,
  fetchEvalRuns,
  downloadEvalResume,
} from '../api';

const TOKEN = 'fake-id-token';

function mockFetch(response: Partial<Response>) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, ...response });
  vi.stubGlobal('fetch', fn);
  return fn;
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe('admin model API', () => {
  it('requests tool-capable models by default and sends the bearer token', async () => {
    const fetchMock = mockFetch({ json: async () => ({ models: [{ id: 'a/b' }] }) });
    const models = await fetchOpenRouterModels(TOKEN);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/admin/models');
    expect(url).toContain('tools_only=true');
    expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(models).toHaveLength(1);
  });

  it('passes the search query and show-all flag', async () => {
    const fetchMock = mockFetch({ json: async () => ({ models: [] }) });
    await fetchOpenRouterModels(TOKEN, { toolsOnly: false, q: 'qwen' });
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain('tools_only=false');
    expect(url).toContain('q=qwen');
  });

  it('throws forbidden on 403', async () => {
    mockFetch({ ok: false, status: 403 });
    await expect(fetchOpenRouterModels(TOKEN)).rejects.toThrow('forbidden');
  });

  it('surfaces the backend detail message on 503', async () => {
    mockFetch({ ok: false, status: 503, json: async () => ({ detail: 'OpenRouter model list unavailable: down' }) });
    await expect(fetchOpenRouterModels(TOKEN)).rejects.toThrow(/unavailable/);
  });

  it('reads the model config', async () => {
    mockFetch({ json: async () => ({ tasks: { generation: { primary: 'openrouter:a', fallback: null } } }) });
    const cfg = await fetchModelConfig(TOKEN);
    expect(cfg.tasks.generation.primary).toBe('openrouter:a');
  });

  it('PUTs a model config update', async () => {
    const fetchMock = mockFetch({ json: async () => ({ tasks: {} }) });
    await updateModelConfig(TOKEN, 'generation', 'openrouter:new', 'google-gla:fb');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/admin/model-config');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({
      task: 'generation', primary: 'openrouter:new', fallback: 'google-gla:fb',
    });
  });
});

describe('admin eval API', () => {
  it('POSTs a run and returns the id', async () => {
    mockFetch({ status: 202, json: async () => ({ run_id: 'run-1' }) });
    const { run_id } = await startEvalRun(TOKEN, {
      models: ['openrouter:a'], jd_ids: ['senior_swe'], custom_jd: null,
      data_source: 'fixture', judge_model: 'google-gla:j', notes: null,
    });
    expect(run_id).toBe('run-1');
  });

  it('surfaces a 400 spec error message', async () => {
    mockFetch({ ok: false, status: 400, json: async () => ({ detail: 'At most 5 models per run' }) });
    await expect(startEvalRun(TOKEN, {
      models: [], jd_ids: [], custom_jd: null, data_source: 'fixture', judge_model: null, notes: null,
    })).rejects.toThrow('At most 5 models per run');
  });

  it('lists runs', async () => {
    mockFetch({ json: async () => ({ runs: [{ id: 'run-1' }] }) });
    expect(await fetchEvalRuns(TOKEN)).toHaveLength(1);
  });

  it('downloads a resume blob with the requested format', async () => {
    const blob = new Blob(['x']);
    const fetchMock = mockFetch({ blob: async () => blob });
    await downloadEvalResume(TOKEN, 'result-1', 'word');
    expect(fetchMock.mock.calls[0][0]).toContain('format=word');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- adminApi`
Expected: FAIL — the functions do not exist

- [ ] **Step 3: Implement**

Append to `frontend/src/services/api.ts`, after `exportAdminLogs`. Factor the shared admin-request behaviour first:

```typescript
async function adminRequest<T>(idToken: string, path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${idToken}`, ...(init.headers || {}) },
  });
  if (res.status === 401 || res.status === 403) throw new Error('forbidden');
  if (!res.ok) {
    let message = `Request failed: ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) message = data.detail;
    } catch { }
    throw new Error(message);
  }
  return res;
}
```

Then each function above, e.g.:

```typescript
export async function fetchOpenRouterModels(
  idToken: string,
  opts: { toolsOnly?: boolean; q?: string } = {}
): Promise<CatalogModel[]> {
  const params = new URLSearchParams({ tools_only: String(opts.toolsOnly ?? true) });
  if (opts.q) params.set('q', opts.q);
  const res = await adminRequest(idToken, `/admin/models?${params}`);
  return (await res.json()).models;
}

export async function updateModelConfig(
  idToken: string, task: ModelTask, primary: string, fallback: string | null
): Promise<ModelConfigResponse> {
  const res = await adminRequest(idToken, '/admin/model-config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, primary, fallback }),
  });
  return res.json();
}
```

`streamEvalRun` uses `fetch` with the bearer header and reads the SSE body via `res.body.getReader()` — `EventSource` cannot send an Authorization header. Parse `event:`/`data:` line pairs and invoke `onCell` for each `cell` event; resolve on `done`. Mirror the parsing already used by `generateResumeStream` in this file rather than writing a second parser.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npm test -- adminApi`
Expected: 10 passed

- [ ] **Step 5: Typecheck, build, and commit**

```bash
cd frontend && npm run build
git add frontend/src/services/api.ts frontend/src/services/__tests__/adminApi.test.ts
git commit -m "feat(frontend): add admin model and eval API client functions"
```

---

### Task 15: Split AdminDashboard into a tab shell

Pure refactor — no behaviour change. Keeps later tasks small.

**Files:**
- Create: `frontend/src/components/admin/StatCard.tsx`, `BarChart.tsx`, `CountTable.tsx`, `index.ts`
- Create: `frontend/src/pages/admin/StatsTab.tsx`
- Modify: `frontend/src/pages/AdminDashboard.tsx`

**Interfaces:**
- Produces:
  - `StatCard({ label, value, hint })`, `BarChart({ data, title })`, `CountTable({ title, rows, keyLabel })` — signatures identical to the current inline versions
  - `StatsTab({ idToken, user })` — owns its own `days` state, stats fetch, export button, and error display
  - `AdminDashboard` — auth gate + tab switcher only; passes a fresh ID token down

- [ ] **Step 1: Extract the three presentational components**

Move `StatCard` (lines 13-21), `BarChart` (23-52) and `CountTable` (54-80) verbatim from `AdminDashboard.tsx` into `frontend/src/components/admin/`, one file each, exported by name, re-exported from `index.ts`. Move `fmtMs` and `WEEKDAYS` into `StatsTab.tsx`.

- [ ] **Step 2: Move the dashboard body into `StatsTab.tsx`**

`StatsTab` receives `{ user }: { user: User }` and contains everything currently rendered inside the `authReady && user && isAdminEmail` block (lines 176-372), plus the `stats`, `loading`, `error`, `days`, `exporting` state and the two effects/handlers that drive them.

- [ ] **Step 3: Reduce `AdminDashboard.tsx` to a shell**

```tsx
type AdminTab = 'stats' | 'models' | 'evals';

const TABS: Array<{ id: AdminTab; label: string }> = [
  { id: 'stats', label: 'Stats' },
  { id: 'models', label: 'Models' },
  { id: 'evals', label: 'Evals' },
];

export function AdminDashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [tab, setTab] = useState<AdminTab>('stats');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const unsub = authStateListener(u => { setUser(u); setAuthReady(true); });
    return () => unsub();
  }, []);

  const isAdminEmail = (user?.email || '').toLowerCase() === ADMIN_EMAIL;
  // ...header, sign-in and access-denied blocks unchanged...

  return (
    // ...
    {authReady && user && isAdminEmail && (
      <>
        <nav className="flex gap-1 border-b border-neutral-200 dark:border-neutral-800">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-2 text-sm border-b-2 -mb-px ${tab === t.id
                ? 'border-primary-500 text-primary-500'
                : 'border-transparent text-neutral-500 hover:text-neutral-300'}`}
            >
              {t.label}
            </button>
          ))}
        </nav>
        {tab === 'stats' && <StatsTab user={user} />}
        {tab === 'models' && <ModelsTab user={user} />}
        {tab === 'evals' && <EvalsTab user={user} />}
      </>
    )}
    // ...
  );
}
```

For this task, stub `ModelsTab` and `EvalsTab` as one-line placeholders that render "Coming in the next task" — Tasks 16 and 17 replace them.

- [ ] **Step 4: Verify no behaviour changed**

Run: `cd frontend && npm run build && npm test`
Expected: build succeeds, existing tests pass. Open `/admin` in `npm run dev`, sign in, confirm the Stats tab renders exactly as before.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AdminDashboard.tsx frontend/src/pages/admin frontend/src/components/admin
git commit -m "refactor(frontend): split AdminDashboard into tabs and shared components"
```

---

### Task 16: ModelsTab and the model picker

**Files:**
- Create: `frontend/src/components/admin/ModelPicker.tsx`
- Create: `frontend/src/pages/admin/ModelsTab.tsx` (replacing the placeholder)

**Interfaces:**
- Consumes: `fetchModelConfig`, `updateModelConfig`, `fetchOpenRouterModels`, `CatalogModel`, `ModelConfigResponse` (Task 14); `Dialog`, `Input`, `Button` from `components/ui`
- Produces:
  - `ModelPicker({ open, idToken, initialValue, onSelect, onClose })` — modal; `onSelect(modelString: string)`
  - `ModelsTab({ user })`

- [ ] **Step 1: Build `ModelPicker`**

A `Dialog` containing: a search `Input` (debounced 250ms, passed to `fetchOpenRouterModels` as `q`), a "tool-capable only" checkbox defaulting to checked, a scrollable list of catalog rows, and a free-text `Input` with a "Use this" button for non-OpenRouter models.

Each row shows the model id, name, context length formatted as `128k`, and `$0.20 / $0.80 per Mtok`. Rows where `supports_tools` is false (visible only with the checkbox cleared) get an amber "no tool support" chip and this warning text: `Resume generation needs tool calling — this model will fail unless it is only used for import.`

Loading state uses `Spinner`. A `CatalogUnavailable` 503 renders the error text plus: `Free-text entry still works.` — the free-text field must stay usable when the catalog is down.

- [ ] **Step 2: Build `ModelsTab`**

Fetches `fetchModelConfig` on mount using a fresh `user.getIdToken()`. Renders three cards in a `grid md:grid-cols-3 gap-4`, one per task, each showing:

- Task name and a one-line description: generation = "Writes the resume. Needs tool calling.", translation = "Translates non-English resumes.", import = "Extracts data from uploaded resume PDFs."
- Primary slot: current model string in `font-mono text-xs`, `Change` button opening `ModelPicker`.
- Fallback slot: same, plus a `Clear` button that sets fallback to `null`.
- Footer line: `Updated {updated_at} by {updated_by}` or `Never changed (using environment default)`.

Selecting a model calls `updateModelConfig`, replaces state with the response, and shows a success toast via `use-toast`. Errors render inline in red and leave the previous value on screen.

The card skeleton:

```tsx
const TASK_META: Array<{ id: ModelTask; label: string; blurb: string }> = [
  { id: 'generation', label: 'Generation', blurb: 'Writes the resume. Needs tool calling.' },
  { id: 'translation', label: 'Translation', blurb: 'Translates non-English resumes.' },
  { id: 'import', label: 'Import', blurb: 'Extracts data from uploaded resume PDFs.' },
];

function ModelSlot({ label, value, onChange, onClear }: {
  label: string; value: string | null; onChange: () => void; onClear?: () => void;
}) {
  return (
    <div className="mt-3">
      <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="font-mono text-xs break-all mt-1">{value ?? 'None'}</p>
      <div className="flex gap-2 mt-1">
        <button onClick={onChange} className="text-xs text-primary-500 hover:underline">Change</button>
        {onClear && value && (
          <button onClick={onClear} className="text-xs text-neutral-500 hover:underline">Clear</button>
        )}
      </div>
    </div>
  );
}
```

Each task card renders `<ModelSlot label="Primary" .../>` and `<ModelSlot label="Fallback" ... onClear={...} />`, with the picker's `onSelect` calling:

```tsx
const applyModel = async (task: ModelTask, slot: 'primary' | 'fallback', model: string | null) => {
  const current = config!.tasks[task];
  const primary = slot === 'primary' ? model! : current.primary;
  const fallback = slot === 'fallback' ? model : current.fallback;
  try {
    setConfig(await updateModelConfig(await user.getIdToken(), task, primary, fallback));
    toast({ title: `${task} model updated` });
  } catch (e: any) {
    setError(e.message);
  }
};
```

- [ ] **Step 3: Verify in the running app**

Run: `cd frontend && npm run dev` with the backend running. On the Models tab: open the picker, search `gemini`, confirm only tool-capable models appear by default, select one for translation, reload the page, confirm the choice persisted.

- [ ] **Step 4: Build and commit**

```bash
cd frontend && npm run build && npm test
git add frontend/src/pages/admin/ModelsTab.tsx frontend/src/components/admin/ModelPicker.tsx
git commit -m "feat(frontend): add admin model configuration tab"
```

---

### Task 17: EvalsTab — new run and live progress

**Files:**
- Create: `frontend/src/pages/admin/EvalsTab.tsx` (replacing the placeholder)

**Interfaces:**
- Consumes: `fetchEvalFixtures`, `startEvalRun`, `streamEvalRun`, `EvalResult` (Task 14); `ModelPicker` (Task 16)
- Produces: `EvalsTab({ user })`; internal state `{ selectedModels: string[]; selectedJds: string[]; customJd: string; dataSource: 'fixture' | 'mine'; cells: Record<string, EvalResult>; runId: string | null }`

- [ ] **Step 1: Build the new-run form**

- **Models**: chips for each selected model with an `x` to remove, plus an `Add model` button opening `ModelPicker`. Disable `Add model` at 5 selections with the hint `Maximum 5 models per run.`
- **Job descriptions**: a checkbox per fixture from `fetchEvalFixtures` showing `label` and `preview`, plus a `Textarea` for a custom JD. Selecting fixtures disables the textarea and vice versa — the backend rejects both.
- **Data source**: radio pair — `Fixture profile (deterministic)` and `My stored profile`. The latter sends `data_source: 'user:' + user.uid`.
- **Cost line**, always visible above the button: `{models} models x {jds} job descriptions = {cells} generations, each with one judge call.`
- **Run button**: disabled when the cell count is 0 or above 20, or while a run is in flight.

- [ ] **Step 2: Build the live grid**

On submit, call `startEvalRun`, then `streamEvalRun(idToken, runId, onCell)`. Render a table with one row per model and one column per JD. Each cell shows a `Spinner` while pending; on arrival, the composite score in large type, `PASS`/`FAIL` from `schema_passed`, and the duration. Error cells show a red `ERROR` with the message on hover (`title` attribute). A cell with `fallback_used` gets an amber `fallback` chip.

Above the grid, a progress line: `{done} / {total} cells complete`.

Cell keying and submission:

```tsx
const cellKey = (model: string, jdId: string) => `${model}::${jdId}`;

const jdIdsForRun = customJd.trim() ? ['custom'] : selectedJds;
const totalCells = selectedModels.length * jdIdsForRun.length;

const start = async () => {
  const idToken = await user.getIdToken();
  setCells({});
  try {
    const { run_id } = await startEvalRun(idToken, {
      models: selectedModels,
      jd_ids: customJd.trim() ? [] : selectedJds,
      custom_jd: customJd.trim() || null,
      data_source: dataSource === 'mine' ? `user:${user.uid}` : 'fixture',
      judge_model: judgeModel,
      notes: null,
    });
    setRunId(run_id);
    await streamEvalRun(idToken, run_id, cell => {
      setCells(prev => ({ ...prev, [cellKey(cell.model, cell.jd_id)]: cell }));
    });
  } catch (e: any) {
    setError(e.message);
  } finally {
    setRunId(null);
  }
};
```

The cost line renders as:

```tsx
<p className="text-xs text-neutral-500">
  {selectedModels.length} models × {jdIdsForRun.length} job descriptions = {totalCells} generations,
  each with one judge call.
</p>
```

- [ ] **Step 3: Verify against the running backend**

Start a run with two cheap models (`google-gla:gemini-2.5-flash-lite` and one OpenRouter tool-capable model) against one fixture JD. Confirm cells fill in independently as they land rather than all at the end, and that the run survives a page that stays open for the full duration.

- [ ] **Step 4: Build and commit**

```bash
cd frontend && npm run build && npm test
git add frontend/src/pages/admin/EvalsTab.tsx
git commit -m "feat(frontend): add eval run form and live progress grid"
```

---

### Task 18: EvalsTab — results, history, and comparison

**Files:**
- Create: `frontend/src/components/admin/EvalResults.tsx`
- Modify: `frontend/src/pages/admin/EvalsTab.tsx`

**Interfaces:**
- Consumes: `fetchEvalRuns`, `fetchEvalRun`, `fetchEvalComparison`, `downloadEvalResume`, `updateModelConfig` (Task 14)
- Produces:
  - `ResultsTable({ results, idToken, onPromote })`
  - `RunHistory({ idToken, onOpenRun })`
  - `ModelComparison({ idToken })`

- [ ] **Step 1: Build `ResultsTable`**

Sortable by any numeric column (click header to toggle direction); default sort is composite descending. Columns: model, JD, status, schema, ATS, judge, composite, latency, tokens. Each row expands to show:

- The judge's `reasoning` text.
- `missing_keywords` as chips.
- The generated resume: title, professional summary, each experience entry with its bullets, skills, education — rendered from `resume_json`, not a raw JSON dump.
- Two download buttons calling `downloadEvalResume(idToken, result.id, 'word' | 'latex')`, triggering a browser download via the object-URL pattern already used by `handleExport` in the old dashboard.
- A `Promote to active` button opening a confirm dialog: `Use {model} for resume generation from now on?` On confirm, call `updateModelConfig(idToken, 'generation', model, currentFallback)` and toast the result.

- [ ] **Step 2: Build `RunHistory`**

Reverse-chronological table from `fetchEvalRuns`: when, who, status chip (`complete` green / `running` blue / `failed` red / `interrupted` amber), models (first two plus `+N`), data source, JD count. Clicking a row calls `fetchEvalRun` and renders its `ResultsTable` below.

- [ ] **Step 3: Build `ModelComparison`**

Table from `fetchEvalComparison`, sorted by `avg_composite` descending: model, runs, cells, success rate as a percentage, avg composite / schema / ATS / judge, avg latency, last run date. Include the caption: `Aggregated across every stored eval result, including older runs.`

- [ ] **Step 4: Wire the three panes into `EvalsTab`**

Sub-tabs within the Evals tab: `New run` (Task 17's form + live grid), `History`, `Compare`. After a run completes, switch the live grid to a `ResultsTable` of the finished cells so the user lands on the detail view without navigating.

- [ ] **Step 5: Verify end to end**

With the backend running: complete a run, expand a result, read the generated resume, download the .docx and open it, promote a model, then switch to the Models tab and confirm the generation primary changed. Reload and confirm the run appears in History and its cells in Compare.

- [ ] **Step 6: Build and commit**

```bash
cd frontend && npm run build && npm test
git add frontend/src/components/admin/EvalResults.tsx frontend/src/pages/admin/EvalsTab.tsx
git commit -m "feat(frontend): add eval results, history, and model comparison views"
```

---

### Task 19: Phase 3 documentation and final verification

**Files:**
- Modify: `frontend/CLAUDE.md`, `CLAUDE.md` (root)

- [ ] **Step 1: Document the dashboard**

In `frontend/CLAUDE.md`, update the components section: `AdminDashboard` is now an auth gate + tab shell over `pages/admin/{StatsTab,ModelsTab,EvalsTab}`, with `components/admin/` holding the shared presentational pieces and `ModelPicker` / `EvalResults`. Add the new `api.ts` functions to the API Service list. Note that `ResumeRequestPayload` no longer carries `model`.

- [ ] **Step 2: Remove the dead `model` field**

Delete `model` from `ResumeRequestPayload` in `frontend/src/services/api.ts` and from any caller that sets it (grep `model:` in `src/pages/Home.tsx`). The backend has never read it.

- [ ] **Step 3: Full verification**

```bash
cd backend && pytest -q
cd ../frontend && npm test && npm run build
```

Expected: backend suite green, frontend tests green, build succeeds with no new type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/CLAUDE.md CLAUDE.md frontend/src/services/api.ts frontend/src/pages/Home.tsx
git commit -m "docs: document the admin dashboard tabs and drop the unused model payload field"
```

---

## Verification Checklist

Before calling the feature done:

- [ ] `cd backend && pytest -q` — all green
- [ ] `cd frontend && npm test && npm run build` — all green
- [ ] Generate a resume end to end; `generation_events` has `requested_model` and `fallback_used` populated
- [ ] Set a deliberately broken model (e.g. a non-tool-capable OpenRouter model) as generation primary with a working fallback; generate; confirm the user gets a resume and the dashboard shows a non-zero fallback rate
- [ ] Run an eval over 2 models x 1 JD; confirm cells stream in, results persist, and the run appears in History after a page reload
- [ ] Download a generated eval resume as .docx and open it
- [ ] Promote a model from an eval result and confirm the Models tab reflects it
- [ ] Restart the backend mid-run; confirm the run is marked `interrupted` rather than staying `running`
