# Admin Model Management & In-Dashboard Model Evaluation

**Date:** 2026-08-10
**Status:** Approved design

## Problem

Production generations are failing with two related errors:

```
openrouter:qwen/qwen3-coder-30b-a3b-instruct — Exceeded maximum output retries (3)
openrouter:qwen/qwen3-coder-30b-a3b-instruct — status_code: 400, 'Provider returned error'
  Alibaba:      The "function.arguments" parameter of the code model must be in JSON format.
  DigitalOcean: Expecting value: line 1 column 38 (char 37)
  SiliconFlow:  "messages" in request are illegal.
```

Root cause: OpenRouter routes the request to providers that cannot handle the
tool-call / structured-output parameters we send. When a provider hard-rejects,
we get a 400; when it accepts but emits malformed tool arguments, pydantic-ai
burns all three output retries and raises `UnexpectedModelBehavior`.

Three structural problems make this worse than it needs to be:

1. **The model is frozen at import time.** `llm/agent.py:38` reads
   `DEFAULT_MODEL` from the environment into a module constant. Changing the
   model requires an env change and a redeploy. `ResumeRequest`
   (`api/schemas.py:4`) does not even accept a `model` field, so the frontend's
   `model` payload field is silently ignored.
2. **No resilience.** A bad model or a bad provider fails the user's request
   outright.
3. **Evaluating a candidate model requires a local dev environment.** The
   harness exists (`tests/evaluators/`, `tests/integration/test_multi_model.py`)
   but is only reachable from a terminal with the repo checked out, and its
   results are printed to stdout and lost.

## Goals

- Change the model for each LLM task from the admin dashboard, at runtime, with
  no redeploy.
- Choose from OpenRouter's live model feed, filtered to models that can actually
  do the job.
- Stop bad models/providers from surfacing as user-facing failures.
- Run the evaluation suite against candidate models from the dashboard, see the
  actual generated resume, and keep the results for future reference.

## Non-goals

- Per-end-user model selection. Model choice stays a global, admin-controlled
  setting.
- A job queue / worker infrastructure. Eval runs are asyncio background tasks in
  the API process.
- Cost accounting beyond token counts recorded per eval result.

---

## Phase 1 — Runtime model configuration and hardening

Independently shippable; on its own it fixes the production errors.

### `app_settings` table

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by  TEXT
);
```

Created in `DBStorage.init_schema()` alongside the existing tables. Three keys:
`model.generation`, `model.translation`, `model.import`. Each value:

```json
{ "primary": "openrouter:...", "fallback": "google-gla:gemini-2.5-flash-lite" }
```

`fallback` may be `null`, meaning no fallback for that task.

### `backend/llm/model_config.py`

The single reader of that table.

```python
@dataclass(frozen=True)
class TaskModels:
    primary: str
    fallback: str | None

@dataclass(frozen=True)
class ModelConfig:
    generation: TaskModels
    translation: TaskModels
    import_: TaskModels

def get_model_config() -> ModelConfig: ...          # TTL-cached
def set_task_models(task, primary, fallback, updated_by) -> None:  # invalidates cache
```

- In-process cache with a ~30s TTL, so per-request reads are cheap and every
  worker converges within 30s of an admin change.
- A missing row is seeded from environment variables — `DEFAULT_MODEL` for
  generation, and optional `TRANSLATION_MODEL` / `IMPORT_MODEL` falling back to
  `DEFAULT_MODEL`. Env is the bootstrap default only; it never overrides a
  stored value.
- If the database is unreachable, fall back to the env values and log a warning
  rather than failing the generation.

### Agent layer (`llm/agent.py`)

- `generate()`, `translate()`, `extract_resume_fields()` resolve `model=None`
  from `get_model_config()` instead of the `DEFAULT_MODEL` constant. An explicit
  `model=` argument still wins — that is what the eval runner and the tests pass.
- `normalize_model_name(None)` currently returns `DEFAULT_MODEL`; resolution
  moves to the call sites so `None` can mean "ask the config".
- `_model_settings()` adds provider routing for OpenRouter models, alongside the
  existing reasoning-off setting:

  ```python
  OpenRouterModelSettings(
      openrouter_reasoning={"enabled": False},
      openrouter_provider={"require_parameters": True},
  )
  ```

  Verified against pydantic-ai 2.27: `OpenRouterProviderConfig` is a `TypedDict`
  with a `require_parameters: bool` field. This makes OpenRouter skip providers
  that do not support the tool/structured-output parameters we send, which is
  the direct cause of the observed 400s.

- **Two-layer fallback.** These are separate mechanisms because they catch
  different failures:
  1. `FallbackModel(primary, fallback, fallback_on=(ModelAPIError,))` handles
     transport/provider errors (`ModelHTTPError` subclasses `ModelAPIError`).
  2. An explicit `except UnexpectedModelBehavior` around the agent run re-runs
     once on the fallback model. This is required because "Exceeded maximum
     output retries" is raised in `pydantic_ai._agent_graph`, above the model
     layer, where `FallbackModel` never sees it.

  Both paths log at WARNING and set a `fallback_used` flag on the result. If no
  fallback is configured, or the fallback also fails, the original exception
  propagates unchanged.

### Bot (`bot.py`)

`self.model` becomes `self.generation_model` and `self.translation_model`, since
the two are now separately configurable. The two `bot.model` references in
`api/routers/resume.py` (lines 179, 181, 314, 333) follow.

### `generation_events`

Add two columns (idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`):

- `requested_model TEXT` — what the config asked for.
- `fallback_used BOOLEAN NOT NULL DEFAULT FALSE`.

`model` keeps its current meaning: the model that actually produced the output.
`get_admin_stats()` gains a fallback rate so a silently-degrading primary is
visible on the dashboard rather than only in logs.

---

## Phase 2 — OpenRouter catalog, eval runner, storage, endpoints

### `backend/llm/openrouter_catalog.py`

`GET https://openrouter.ai/api/v1/models` via httpx, 1h in-process TTL cache.
Normalized entry:

```python
{ "id", "name", "context_length", "prompt_price", "completion_price",
  "supports_tools", "supports_structured_outputs" }
```

`supports_tools` / `supports_structured_outputs` are derived from the feed's
`supported_parameters` array. Fetch failure raises a typed error; the endpoint
translates it to 503 with a clear message and the UI degrades to its free-text
field.

### `backend/evals/` — shared harness

Moved out of `tests/` (via `git mv`, no logic changes beyond those noted) so both
the API and pytest import the same code:

- `evals/evaluators/{schema_evaluator,ats_evaluator,llm_judge,report}.py` — from
  `tests/evaluators/`. `LLMJudge` gains an async `aevaluate()`; its existing
  `run_sync()` would deadlock when called from inside the API's running event
  loop. The sync method stays for CLI use.
- `evals/fixtures.py` — the three JD fixtures (from `tests/fixtures/job_descriptions.py`)
  plus the stub profile context and `StubVectorStore` (currently in
  `tests/conftest.py`). `tests/conftest.py` re-exports them so existing fixtures
  keep working.
- `evals/runner.py`:

  ```python
  @dataclass
  class EvalSpec:
      models: list[str]              # <= 5
      jd_ids: list[str]              # fixture ids
      custom_jd: str | None          # mutually exclusive with jd_ids
      data_source: str               # "fixture" | "user:<uid>"
      judge_model: str
      created_by: str

  async def run_eval(spec, *, on_cell=None) -> str:  # returns run_id
  ```

  One cell per (model, JD): `Bot(...).generate_resume(jd)` with the cell's model
  explicitly passed, then schema + ATS + judge evaluation, then persist the row
  and invoke `on_cell`. Concurrency bounded by `asyncio.Semaphore(3)`. Hard cap
  of 20 cells per run — with 5 models and the 3 current fixture JDs the real
  maximum is 15, so the cap leaves headroom for another fixture without a code
  change. A failing cell records its error and does not abort the run.

  `data_source="user:<uid>"` uses the real `PGVectorStore` for that user;
  `"fixture"` uses `StubVectorStore`.

- `tests/integration/test_multi_model.py` becomes a thin wrapper over
  `run_eval`, driven by `--models`, so the CLI and dashboard paths cannot drift.
- Existing importers of the moved modules are updated: `tests/unit/test_evaluators.py`,
  `tests/integration/test_resume_generation.py`, and
  `tests/integration/test_resume_import_real.py`.

### Storage

```sql
CREATE TABLE IF NOT EXISTS eval_runs (
    id           UUID PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    created_by   TEXT NOT NULL,           -- admin email
    status       TEXT NOT NULL,           -- running | complete | failed | interrupted
    data_source  TEXT NOT NULL,
    judge_model  TEXT,
    models       JSONB NOT NULL,
    jd_ids       JSONB NOT NULL,
    custom_jd    TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS eval_results (
    id                UUID PRIMARY KEY,
    run_id            UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    model             TEXT NOT NULL,
    jd_id             TEXT NOT NULL,
    status            TEXT NOT NULL,      -- success | error
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
CREATE INDEX IF NOT EXISTS idx_eval_results_run   ON eval_results(run_id);
CREATE INDEX IF NOT EXISTS idx_eval_results_model ON eval_results(model);
```

On API startup, any run still marked `running` is set to `interrupted` — a
container restart would otherwise leave ghost runs.

### Endpoints

All under `/resume/admin`, all gated by the existing `require_admin` dependency.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/models?tools_only=&q=` | OpenRouter catalog |
| GET | `/model-config` | current per-task primary/fallback + updated_at/by |
| PUT | `/model-config` | set primary/fallback for one or more tasks |
| POST | `/model-config/promote` | set a task's primary from an eval result id |
| GET | `/evals/fixtures` | available JD fixtures and data sources |
| POST | `/evals` | start a run, returns `run_id` |
| GET | `/evals/{id}/stream` | SSE progress; one event per completed cell |
| GET | `/evals` | run history (paginated) |
| GET | `/evals/{id}` | run detail with all results |
| GET | `/evals/compare?models=` | per-model aggregate across all stored runs |
| GET | `/evals/results/{id}/download?format=word\|latex` | rendered resume file |

The download route feeds the stored `resume_json` through the production
`WordResumeWriter` / `LatexResumeWriter`, so the reviewed artifact is a real
output file rather than a preview approximation.

`PUT /model-config` validates the model string shape (`provider:name`) and, for
OpenRouter ids, warns (does not block) when the catalog says the model lacks
tool support.

---

## Phase 3 — Dashboard UI

`AdminDashboard.tsx` (378 lines today) becomes a tab shell over three pages:

- `pages/admin/StatsTab.tsx` — the current dashboard, moved as-is, plus a
  fallback-rate stat card.
- `pages/admin/ModelsTab.tsx`
- `pages/admin/EvalsTab.tsx`

`StatCard`, `BarChart`, and `CountTable` move to `components/admin/` and are
shared across tabs.

### ModelsTab

Three cards — generation, translation, import — each with a primary slot and a
fallback slot showing the live value and who last changed it. Clicking a slot
opens a searchable picker over the OpenRouter catalog:

- Tool-capable models only by default, with a "show all" toggle; models lacking
  tool support are flagged when revealed.
- Columns: id, context length, prompt/completion price per Mtok.
- A free-text field accepts any pydantic-ai model string (e.g.
  `google-gla:gemini-3.1-flash-lite`) for non-OpenRouter providers.

Saving writes through `PUT /model-config`.

### EvalsTab

- **New run** — multi-select models (max 5), JD fixture checkboxes or a paste
  box, fixture-vs-my-account data source toggle, judge model. Displays the cell
  count before the run button so the cost is visible up front.
- **Live run** — a model x JD grid filled in over SSE; each completed cell shows
  composite score, latency, and pass/fail.
- **Results** — sortable table (schema / ATS / judge / composite / latency /
  tokens), expandable full resume per cell, .docx/.pdf download, and "Promote to
  active" on any result.
- **History** — reverse-chronological run list, plus a compare view aggregating
  every stored result per model so older evaluations stay on the board.

### API client

New functions in `src/services/api.ts`, all taking a Firebase ID token like the
existing admin calls: `fetchOpenRouterModels`, `fetchModelConfig`,
`updateModelConfig`, `promoteModel`, `fetchEvalFixtures`, `startEvalRun`,
`streamEvalRun`, `fetchEvalRuns`, `fetchEvalRun`, `fetchEvalComparison`,
`downloadEvalResume`.

The unused `model` field on `ResumeRequestPayload` is removed at the same time —
the backend has never read it, and leaving it implies a per-request model choice
that is explicitly a non-goal.

---

## Testing

All unit tests run offline — `conftest.py` sets
`pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` without `--real-ai`, and that
guarantee is preserved.

**Backend unit:**
- `model_config`: env seeding, TTL cache hit/expiry, cache invalidation on write,
  database-unreachable degradation.
- Fallback layer 1: a `FunctionModel` raising `ModelHTTPError` falls back and
  succeeds; `fallback_used` is set.
- Fallback layer 2: a `FunctionModel` producing invalid output until retries are
  exhausted (`UnexpectedModelBehavior`) falls back and succeeds. This is the
  regression test for the reported production error.
- No fallback configured, or fallback also fails: original exception propagates.
- `openrouter_catalog`: parsing, `supports_tools` derivation, TTL behaviour,
  fetch failure, all with mocked httpx.
- `evals/runner`: full run on `TestModel` — cells persisted, `on_cell` fired per
  cell, one failing cell does not abort the run, cap enforced.
- Admin endpoints: authz (non-admin rejected), payload validation, promote flow.
- New `DBStorage` methods, following the existing `tests/unit/test_db_storage.py`
  pattern.

**Frontend:** vitest coverage for the new `api.ts` functions, matching
`src/services/__tests__/api.test.ts`.

**Integration (`--real-ai`):** the existing multi-model comparison test, now
running through `evals/runner`.

---

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Admin selects a model that cannot tool-call | Picker defaults to tool-capable; `PUT` warns; the fallback catches the failure at runtime |
| Eval run costs money unexpectedly | Cell count shown before the run; hard cap of 20 cells; concurrency bounded at 3 |
| Container restart mid-run | Startup marks orphaned runs `interrupted` |
| `resume_json` bloats the database | One row per model x JD, admin-triggered only; volume is inherently small |
| Config read on every generation | 30s TTL cache; env fallback if the database is unavailable |
