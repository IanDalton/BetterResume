# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Frontend (S:/Github/BetterResume/frontend/)
```bash
npm run dev        # Start Vite dev server
npm run build      # Production build
npm run preview    # Preview production build
npm test           # Run vitest unit tests
```

### Backend (S:/Github/BetterResume/backend/)
```bash
# Run API server
uvicorn api.main:app --reload

# Run all tests
pytest

# Run a single test file
pytest tests/unit/test_agent.py

# Run with verbose output
pytest -v tests/

# Run tests that hit real AI APIs (skipped by default)
pytest --real-ai

# Docker local dev stack (postgres + embedding service + backend)
docker-compose up
```

## Architecture

BetterResume generates ATS-optimized resumes tailored to job descriptions using LLMs and semantic search.

### Backend: Python FastAPI + pydantic-ai

**Entry points:**
- `api/main.py` — FastAPI app, CORS, database connection pool lifecycle
- `bot.py` — `Bot` class; orchestrates resume generation around the `llm/agent.py` module agents

**Request flow for resume generation:**
1. Frontend POST `/resume/generate-resume/{user_id}` → `api/routers/resume.py`
2. Router instantiates `Bot(user_id, vector_store=...)` with a per-user `PGVectorStore`
3. The generation agent's `search_experience` tool does semantic search against the user's stored experience/skills in pgvector; `get_latest_job_experience` anchors the timeline
4. pydantic-ai calls the configured generation model with retrieved context + job description, returning a validated `ResumeOutputFormat`
5. The router renders the output file with `WordResumeWriter` or `LatexResumeWriter` from `resume/`

**Key subsystems:**
- `llm/model_config.py` — runtime per-task model configuration (`generation`/`translation`/`import`/`judge`), loaded from `app_settings` table; env vars seed the values only if no stored setting exists. Models are runtime-configurable via the admin dashboard rather than env-fixed.
- `llm/model_names.py` — provider-prefix normalization (`google-gla:`/`google_genai:` → `google:`) and validation against pydantic-ai's provider registry, applied wherever a model string is stored or resolved
- `llm/model_routing.py` — the OpenRouter routing demands we send (`require_parameters`, reasoning disabled, forced `tool_choice`) disqualify many capable models; a rejected request is retried with one demand dropped and the concession remembered, so those models work instead of failing every request
- `llm/model_probe.py` — one minimal request against a model in the production shape, run before the dashboard stores it. The OpenRouter catalog advertises capabilities individual endpoints don't honour, so this is the only reliable way to know whether a model works, works with a routing concession, or not at all.
- `llm/agent.py` — module-level pydantic-ai Agents (`generation_agent` with tools, `translation_agent` without) plus `generate()`/`translate()` entry functions; retrieval forcing via output validator (`ModelRetry`)
- `llm/reviewer.py` — `review_agent` + `review()`: user-facing LLM review of a generated resume against its job description (1-10 relevance/quality/coherence, strengths, concrete recommendations per section, keywords worth adding), written in the UI language. Runs on the `judge` task model so a resume is never graded by the model that wrote it; prompt in `prompts/review_prompt.txt`
- `llm/resume_analysis.py` — `analyze_resume()`: the offline `ATSEvaluator` score (0-100, keyword coverage, structured formatting issues) plus the review above, combined into one `ResumeAnalysis`. A failed review still returns the ATS part with `review_error` set. Served by `POST /resume/analyze-resume/{user_id}` (takes the generation `result` back from the client, stateless) and `POST /resume/analyze-resume-pdf/{user_id}` (an uploaded resume PDF, parsed by the import pipeline and mapped through `utils/imported_resume.py`). Every analysis is persisted to `resume_analyses` (attributed to the user's latest generation model, or `imported`) for the admin Stats tab
- "Apply improvements": `ResumeRequest.improvements` carries the review recommendations the user ticked into a regeneration; `llm/agent.py::improvements_block` appends them to the generation prompt and `api/utils.py::_build_result_signature` folds them into the result-cache key so the regeneration is never served from cache
- `llm/vector_store.py` — `PGVectorStore`: pgvector-backed semantic store
- `llm/embeddings.py` — `EmbeddingClient`: httpx client for the OpenAI-compatible TEI embedding service
- `llm/openrouter_catalog.py` — OpenRouter model catalog client (tool-capable models with pricing)
- `evals/` — Evaluation harness: deterministic fixtures, evaluation runners (schema/ATS/LLM-judge scoring), shared by CLI integration tests and admin dashboard
- `resume/` — Format-specific writers (Word, LaTeX) over a shared base writer
- `models/` — Pydantic models for `Resume`, `JobExperience`, `Education`, `Skill`
- `utils/db_storage.py` — PostgreSQL interaction (pgvector queries, user data, generation events, eval runs/results, admin stats)
- `api/auth.py` — Firebase ID-token verification (PyJWT against Google certs); `require_admin` dependency
- `api/routers/admin.py` — admin endpoints: stats, logs, model catalog, model config, evaluation runs/results (all admin-only)
- `prompts/` — Plain-text prompt templates loaded at runtime

**Database:** PostgreSQL with pgvector extension. Connection pool managed via `psycopg-pool`. User experience data is stored as vector embeddings for semantic retrieval. `generation_events` records every generation (model, format, language, duration, status) for the admin dashboard.

**Required environment variables** (see `.env.template`):
- `DEFAULT_MODEL` — default LLM for generation/translation/import (seeded into `app_settings`; runtime-configurable via admin dashboard). `JUDGE_MODEL` seeds the eval judge separately, so a model is never asked to grade its own output.
- `DB_*` — PostgreSQL credentials
- `EMBEDDING_SERVICE_URL` — OpenAI-compatible TEI embedding service endpoint
- `FIREBASE_PROJECT_ID` — verify Firebase ID tokens for the admin dashboard
- `ADMIN_EMAIL` — admin dashboard allowlist (defaults to daltioan@gmail.com)
- `STRIPE_*` — Stripe public/secret keys
- `OPENROUTER_API_KEY` — the only LLM credential a default deployment needs: every shipped model routes through OpenRouter (`openrouter:google/gemini-2.5-flash-lite`)
- `GEMINI_API_KEY` — optional; only if a task is pointed at a `google:` model instead of OpenRouter (bridged to `GOOGLE_API_KEY` in `api/main.py`)
- `LOG_LEVEL` / `LOG_FILE` — optional logging configuration

### Frontend: React 18 + TypeScript + Vite + Tailwind

**Entry points:**
- `src/main.tsx` — React root
- `src/App.tsx` — React Router v7 routes (`/`, `/donate`, `/donate-checkout`, `/thank-you`, `/donate-success`, `/admin`)

**Auth:** Firebase authentication via `AuthGate` component wrapping all protected routes. Firebase config lives in `src/services/firebase.ts`.

**Key pages/components:**
- `Home` — main UI triggering resume generation; after a generation, an "ATS analysis" card under the preview calls `analyzeResume` and renders `components/ResumeAnalysisPanel` (ATS + reviewer scores, keyword chips, formatting checks, recommendations with checkboxes and an "Apply N and regenerate" button that re-runs generation with `improvements`, showing score deltas on the next analysis). `components/ExistingResumeAnalyzer` under the job-description box scores an uploaded PDF via `analyzeResumePdf` without generating
- `ProfileEditor` / Entry sections (`PersonalInfoSection`, `ExperienceSection`, `EducationSection`, `LanguagesSection`) — unified data-entry flow
- `ResumeImportDialog` — resume parsing and LinkedIn PDF import
- `Donate` — Stripe payment flow (embedded checkout)
- `AdminDashboard` (`/admin`) — auth gate + tab shell over `pages/admin/{StatsTab,ModelsTab,EvalsTab}`, requiring Firebase sign-in with the admin email; covers generation stats, per-task model configuration, and the eval subsystem

**API communication:** `src/services/api.ts` wraps all backend calls. CSV data format matches backend's `jobs.csv` schema (columns: `type, company, location, role, start_date, end_date, description`).

**Tests:** vitest specs live in `src/services/__tests__/`.

### Infrastructure
- `backend/docker-compose.yml` — local dev: PostgreSQL (pgvector image), HuggingFace embedding service, backend
- `backend/Dockerfile` — production container (Python 3.13-slim)
- `.github/workflows/deploy-frontend.yml` — GitHub Actions deploys frontend to GitHub Pages on push to `main`
