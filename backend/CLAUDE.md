# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run API server (dev)
uvicorn api.main:app --reload

# Run all tests
pytest

# Run a single test file
pytest tests/test_agent.py -v

# Run tests with real AI calls (skipped by default)
pytest --real-ai

# Run tests against specific models, always use cheap models like haiku or gemini flash - lite
pytest --models gemini-2.5-flash-lite, gemini-3.1-flash-lite

# Start full local dev stack (postgres + embedding service + backend)
docker-compose up
```

## Architecture

### Entry Points
- `api/main.py` — FastAPI app setup: CORS (iandalton.dev + localhost allowed), CSP middleware, correlation ID tracking, request timing, lifespan db pool init/cleanup
- `bot.py` — `Bot` class; the core resume generation orchestrator

### Resume Generation Flow
1. `POST /resume/generate` → `api/routers/resume.py`
2. Router constructs a `Bot` instance and calls `generate_resume(jd)` or `generate_resume_progress(jd)` (streaming)
3. `Bot` builds a LangGraph `StateGraph`: **agent → tools → generate** nodes
4. The agent calls `PGVectorTool` to semantically retrieve relevant user experience from pgvector
5. `GeminiAgent` (in `llm/gemini_agent.py`) uses retrieved context + job description to produce structured output
6. `resume/writer.py` dispatches to `WordWriter` or `LatexWriter` to produce the output file

### LLM / Agent Layer (`llm/`)
- `base.py` — Abstract `BaseLLM`; initializes chat models via `langchain.init_chat_model`, builds the StateGraph, supports forced tool calls via `tool_choice="any"`
- `state.py` — LangGraph `State` TypedDict: `messages`, `user_id`, `structured_response`, `remaining_steps`, `require_tool_call`
- `pg_vector_tool.py` — LangChain tool wrapping pgvector similarity search for job/skill retrieval
- `job_experience_tool.py` — Tool for structured job experience lookups
- `gemini_agent.py` — Concrete `BaseLLM` subclass using Google Gemini

### Database (`utils/db_storage.py`)
- Global `_pool` (sync) and `_async_pool` (async) connection pools via `psycopg-pool`
- Pool sizes configurable via env vars: `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`
- pgvector registered on both pools at init time
- `init_db_pool()` called from FastAPI lifespan

### Resume Writers (`resume/`)
- `base_writer.py` — Abstract base with shared formatting logic
- `word_writer.py` — Produces `.docx` via `python-docx`
- `latex_writer.py` — Produces `.tex` / `.pdf` via `pdflatex`
- `writer.py` — Factory that dispatches to the correct writer based on requested format
- `parser.py` — Parses CSV/JSON user data into Pydantic models

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

### Configuration
- `api/config.py` — directory paths (`DATA_DIR`, `OUTPUTS_BASE`, `UPLOADS_BASE`, `PROFILE_PICS_BASE`), supported image types, download signing secret
- `.env.template` — required env vars: `GEMINI_API_KEY`, `DB_HOST/PORT/NAME/USER/PASSWORD`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`

### Testing (`tests/`)
- `conftest.py` — fixtures: `models_under_test`, `sample_resume_output`, `mock_pg_vector_tool` (stub avoiding real Postgres)
- Tests default to mocked AI; use `--real-ai` flag to hit real models
- `pytest.ini` — pytest configuration

### Docker Local Dev (`docker-compose.yml`)
Three services:
- `db` — `pgvector/pgvector:0.8.1-pg18`
- `embeddings` — HuggingFace TEI (`nomic-embed-text-v1.5`) on CPU
- `backend` — built from `Dockerfile`, port 8000, waits on db health
