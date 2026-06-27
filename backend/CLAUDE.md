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
4. The model (Google Gemini via `google-gla:` provider) returns a validated `ResumeOutputFormat`; non-English resumes go through the translation agent
5. The router renders the output file via `WordResumeWriter` or `LatexResumeWriter` (`_make_writer`)
6. Each generation is recorded in `generation_events` (model, format, language, duration, status) for the admin dashboard

### LLM / Agent Layer (`llm/`)
- `agent.py` — module-level pydantic-ai `Agent` singletons: `generation_agent` (tools + structured output) and `translation_agent` (no tools). No model is bound at construction; the `generate()` / `translate()` module functions resolve one per run (default `DEFAULT_MODEL`), so importing never needs credentials. `ResumeDeps` dataclass carries user_id/vector_store/db into tools. Forced retrieval (the old `tool_choice="any"`) is an output validator that raises `ModelRetry` if `search_experience` was never called. `normalize_model_name` maps legacy `google_genai:` prefixes to `google-gla:`.
- `vector_store.py` — `PGVectorStore`: pgvector similarity search / upsert / delete, async-first with sync wrappers
- `embeddings.py` — `EmbeddingClient`: httpx client for the OpenAI-compatible TEI embedding endpoint (`EMBEDDING_SERVICE_URL`)

### Database (`utils/db_storage.py`)
- Global `_pool` (sync) and `_async_pool` (async) connection pools via `psycopg-pool`
- Pool sizes configurable via env vars: `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`
- pgvector registered on both pools at init time
- `init_db_pool()` called from FastAPI lifespan
- `record_generation_event()` / `get_admin_stats()` power the admin dashboard

### Admin (`api/auth.py`, `api/routers/admin.py`)
- `GET /resume/admin/stats?days=N` — aggregated stats (totals, per-day, per-model/format/language, top users, recent requests, donations)
- Gated by `require_admin`: verifies the Firebase ID token (PyJWT + Google securetoken certs, audience = `FIREBASE_PROJECT_ID`) and requires the verified email to equal `ADMIN_EMAIL` (default daltioan@gmail.com)

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
- `.env.template` — required env vars: `GEMINI_API_KEY`, `DB_HOST/PORT/NAME/USER/PASSWORD`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `FIREBASE_PROJECT_ID`, `ADMIN_EMAIL`

### Testing (`tests/`)
- `pytest.ini` — `asyncio_mode = auto`, 120s timeout
- `conftest.py` — fixtures: `models_under_test`, `sample_resume_output`, `stub_vector_store` (in-memory store, no Postgres). Sets `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` unless `--real-ai` is passed, so unit tests can never hit a real LLM
- Unit tests use pydantic-ai `TestModel` / `FunctionModel` (see `tests/unit/test_agent.py`)
- `tests/unit/` — agent, bot, embeddings, vector store, ingest, admin auth/API, db storage, logging, evaluators
- `tests/integration/` — real-AI generation and multi-model comparison (require `--real-ai`)

### Docker Local Dev (`docker-compose.yml`)
Three services:
- `db` — `pgvector/pgvector:0.8.1-pg18`
- `embeddings` — HuggingFace TEI (`nomic-embed-text-v1.5`) on CPU
- `backend` — built from `Dockerfile`, port 8000, waits on db health
