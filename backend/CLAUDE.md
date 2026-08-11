# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run API server (dev)
uvicorn api.main:app --reload

# Run all tests
pytest

# Run a single test file
pytest tests/unit/test_agent.py -v

# Run tests with real AI calls (skipped by default)
pytest --real-ai

# Run tests against specific models, always use cheap models like haiku or gemini flash - lite
pytest --models "google-gla:gemini-2.5-flash-lite,google-gla:gemini-3.1-flash-lite"

# Start full local dev stack (postgres + embedding service + backend)
docker-compose up
```

## Architecture

### Entry Points
- `api/main.py` — FastAPI app setup: CORS (iandalton.dev + localhost allowed), CSP middleware, correlation ID tracking, request timing, lifespan db pool init/cleanup, GEMINI_API_KEY → GOOGLE_API_KEY bridge for pydantic-ai
- `bot.py` — `Bot` class; the core resume generation orchestrator

### Resume Generation Flow
1. `POST /resume/generate-resume/{user_id}` → `api/routers/resume.py`
2. Router constructs a `Bot(user_id, vector_store=..., jobs_csv=...)` with a per-user `PGVectorStore`, then calls `generate_resume(jd)` or `generate_resume_progress(jd)` (streaming); both consume the same internal `_pipeline` generator
3. The pydantic-ai generation agent calls `search_experience` (pgvector retrieval) and `get_latest_job_experience` tools
4. The configured generation model returns a validated `ResumeOutputFormat`; non-English resumes go through the translation agent
5. The router renders the output file via `WordResumeWriter` or `LatexResumeWriter` (`_make_writer`)
6. Each generation is recorded in `generation_events` (model, format, language, duration, status) for the admin dashboard

### LLM / Agent Layer (`llm/`)
- `model_config.py` — runtime per-task model settings (`generation` / `translation` / `import`), stored in the `app_settings` table and TTL-cached for 30s. Env vars (`DEFAULT_MODEL`, `TRANSLATION_MODEL`, `IMPORT_MODEL`, `*_FALLBACK_MODEL`) seed the values and are the last resort if the database is unreachable; a stored value always wins.
- `agent.py` — module-level pydantic-ai `Agent` singletons: `generation_agent` (tools + structured output), `translation_agent` (no tools), and `resume_import_agent` (structured extraction). No model is bound at construction; the `generate()` / `translate()` / `extract_resume_fields()` module functions resolve one per run (default `DEFAULT_MODEL`), so importing never needs credentials. `ResumeDeps` dataclass carries user_id/vector_store/db into tools. Forced retrieval (the old `tool_choice="any"`) is an output validator that raises `ModelRetry` if `search_experience` was never called. `normalize_model_name` maps legacy `google_genai:` prefixes to `google-gla:`. OpenRouter runs set `openrouter_provider={"require_parameters": True}` so OpenRouter skips providers that reject our tool-call parameters. Failures are covered in two layers: `FallbackModel` for `ModelAPIError`, plus an explicit `UnexpectedModelBehavior` catch for output-retry exhaustion (raised above the model layer, where FallbackModel cannot see it).
- `vector_store.py` — `PGVectorStore`: pgvector similarity search / upsert / delete, async-first with sync wrappers
- `embeddings.py` — `EmbeddingClient`: httpx client for the OpenAI-compatible TEI embedding endpoint (`EMBEDDING_SERVICE_URL`)
- `openrouter_catalog.py` — Fetches and caches the OpenRouter model catalog (tool-capable models) for the admin picker; uses `CatalogModel` dataclass with pricing/context info

### Database (`utils/db_storage.py`)
- Global `_pool` (sync) and `_async_pool` (async) connection pools via `psycopg-pool`
- Pool sizes configurable via env vars: `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`
- pgvector registered on both pools at init time
- `init_db_pool()` called from FastAPI lifespan
- `record_generation_event()` / `get_admin_stats()` power the admin dashboard

### Admin (`api/auth.py`, `api/routers/admin.py`)
Auth: `require_admin` dependency verifies Firebase ID token (PyJWT + Google securetoken certs, audience = `FIREBASE_PROJECT_ID`) and requires email = `ADMIN_EMAIL` (default daltioan@gmail.com).

Endpoints (all admin-only):
- `GET /resume/admin/stats?days=N` — aggregated generation statistics
- `GET /resume/admin/logs/export` — all generation events as CSV
- `GET /resume/admin/models?tools_only=true&q=""` — OpenRouter model catalog (normalized list with pricing/capabilities)
- `GET /resume/admin/model-config` — current per-task (generation/translation/import) primary/fallback models with metadata
- `PUT /resume/admin/model-config` — update primary/fallback for one task; stored in `app_settings` table
- `GET /resume/admin/evals/fixtures` — available job-description fixtures and default judge model
- `POST /resume/admin/evals` (status 202) — start an evaluation run in background; returns run_id immediately, streaming cells via `/stream`
- `GET /resume/admin/evals` — past evaluation runs (newest first)
- `GET /resume/admin/evals/compare` — per-model aggregate across all stored eval results
- `GET /resume/admin/evals/{run_id}` — one run with all of its cell results
- `GET /resume/admin/evals/{run_id}/stream` — SSE stream of cells for an in-flight run
- `GET /resume/admin/evals/results/{result_id}/download?format=word` — render a stored eval resume via production writers (Word or LaTeX)

### Evaluation (`evals/`)
- `fixtures.py` — deterministic test inputs: `JD_FIXTURES` (3 job-description fixtures: senior_swe, junior_analyst, product_manager), `StubVectorStore` (in-memory mock returning canned resume context), `STUB_RESUME_CONTEXT` (engineer resume for testing)
- `evaluators/` — four scoring modules:
  - `schema_evaluator.py` — `SchemaEvaluator`: validates structural correctness of `ResumeOutputFormat` (offline, deterministic)
  - `ats_evaluator.py` — `ATSEvaluator`: keyword coverage analysis (offline); scores how well a resume matches a job description
  - `llm_judge.py` — `LLMJudge`: LLM-as-judge scoring (relevance/quality/coherence); requires a real API key
  - `report.py` — `ResumeEvaluationReport`: composite scoring (combines schema/ATS/judge results with weighted formula)
- `runner.py` — `EvalSpec`/`validate_spec`/`run_eval` orchestrate evaluation runs: `MAX_MODELS=5` / `MAX_CELLS=20` / `CONCURRENCY=3`. Each cell generates a resume for one (model, JD) pair, scores it, and persists immediately (failures are logged, not raised). Optionally calls `on_cell` callback (used by admin `/evals` endpoint for SSE streaming). `run_eval` is shared by both the pytest integration test (`tests/integration/test_multi_model.py`) and the admin dashboard.
  - **Multi-worker caveat**: `_EVAL_STREAMS` (per-process, in-memory queues for live results) is not shared across uvicorn/gunicorn workers; a `/stream` request on a different worker will 404 even if the run is in flight elsewhere. Clients must know this.

### Logging (`utils/logging_utils.py`)
- `setup_logging()` — idempotent; `betterresume.*` loggers with request_id/user_id context injection
- `LOG_LEVEL` env sets verbosity; `LOG_FILE` adds a rotating file handler

### Resume Writers (`resume/`)
- `base_writer.py` — Abstract base with shared formatting logic
- `word_writer.py` — Produces `.docx` via `python-docx`
- `latex_writer.py` — Produces `.tex` / `.pdf` via `pdflatex`

### Data Models (`models/`)
Pydantic models: `Resume`, `JobExperience`, `Education`, `Skill`

### API Routers (`api/routers/`)
All mounted under `/resume` prefix:
- `resume.py` — generation endpoints (generate, stream)
- `jobs.py` — CRUD for user job entries
- `profile.py` — user profile & picture upload
- `users.py` — user management
- `health.py` — health check
- `donations.py` — Stripe webhook + payment intent
- `admin.py` — admin statistics (auth required)

### Configuration
- `api/config.py` — directory paths (`DATA_DIR`, `OUTPUTS_BASE`, `UPLOADS_BASE`, `PROFILE_PICS_BASE`), supported image types, download signing secret
- `.env.template` — required env vars: `GEMINI_API_KEY`, `DB_HOST/PORT/NAME/USER/PASSWORD`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `FIREBASE_PROJECT_ID`, `ADMIN_EMAIL`, and model configuration (`DEFAULT_MODEL`, `TRANSLATION_MODEL`, `IMPORT_MODEL`, `*_FALLBACK_MODEL`)
- `app_settings` table — runtime configuration (e.g. active LLM models per task); persisted alongside schema in `utils/db_storage.py`

### Testing (`tests/`)
- `pytest.ini` — `asyncio_mode = auto`, 120s timeout
- `conftest.py` — fixtures: `models_under_test`, `sample_resume_output`, `stub_vector_store` (in-memory store, no Postgres). Sets `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` unless `--real-ai` is passed, so unit tests can never hit a real LLM
- Unit tests use pydantic-ai `TestModel` / `FunctionModel` (see `tests/unit/test_agent.py`)
- `tests/unit/` — agent, bot, embeddings, vector store, ingest, admin auth/API, db storage, logging, eval runner, eval storage, evaluators, model config, OpenRouter catalog
- `tests/integration/` — real-AI generation and multi-model comparison via eval runner (require `--real-ai`); `test_multi_model.py` is a thin wrapper over `evals.runner` so CLI and dashboard measure exactly the same thing

### Docker Local Dev (`docker-compose.yml`)
Three services:
- `db` — `pgvector/pgvector:0.8.1-pg18`
- `embeddings` — HuggingFace TEI (`nomic-embed-text-v1.5`) on CPU
- `backend` — built from `Dockerfile`, port 8000, waits on db health
