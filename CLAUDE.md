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
4. pydantic-ai calls Google Gemini (`google-gla:` provider) with retrieved context + job description, returning a validated `ResumeOutputFormat`
5. The router renders the output file with `WordResumeWriter` or `LatexResumeWriter` from `resume/`

**Key subsystems:**
- `llm/agent.py` — module-level pydantic-ai Agents (`generation_agent` with tools, `translation_agent` without) plus `generate()`/`translate()` entry functions; retrieval forcing via output validator (`ModelRetry`)
- `llm/vector_store.py` — `PGVectorStore`: pgvector-backed semantic store
- `llm/embeddings.py` — `EmbeddingClient`: httpx client for the OpenAI-compatible TEI embedding service
- `resume/` — Format-specific writers (Word, LaTeX) over a shared base writer
- `models/` — Pydantic models for `Resume`, `JobExperience`, `Education`, `Skill`
- `utils/db_storage.py` — PostgreSQL interaction (pgvector queries, user data, generation events, admin stats)
- `api/auth.py` — Firebase ID-token verification (PyJWT against Google certs); `require_admin` dependency
- `api/routers/admin.py` — `/resume/admin/stats` endpoint (admin-only)
- `prompts/` — Plain-text prompt templates loaded at runtime

**Database:** PostgreSQL with pgvector extension. Connection pool managed via `psycopg-pool`. User experience data is stored as vector embeddings for semantic retrieval. `generation_events` records every generation (model, format, language, duration, status) for the admin dashboard.

**Required environment variables** (see `.env.template`):
- `GEMINI_API_KEY` — Google Gemini LLM (bridged to `GOOGLE_API_KEY` for pydantic-ai)
- `DB_*` — PostgreSQL credentials
- `STRIPE_*` — Stripe payment keys
- `FIREBASE_PROJECT_ID` — verify Firebase ID tokens for the admin dashboard
- `ADMIN_EMAIL` — admin dashboard allowlist (defaults to daltioan@gmail.com)
- `LOG_LEVEL` / `LOG_FILE` — optional logging overrides

### Frontend: React 18 + TypeScript + Vite + Tailwind

**Entry points:**
- `src/main.tsx` — React root
- `src/App.tsx` — React Router v7 routes (`/`, `/donate`, `/thank-you`, `/admin`)

**Auth:** Firebase authentication via `AuthGate` component wrapping all protected routes. Firebase config lives in `src/services/firebase.ts`.

**Key pages/components:**
- `OnboardingWizard` — multi-step flow to collect user profile and experience
- `EntryBuilder` — UI for building CSV-structured resume entries
- `Home` — main UI triggering resume generation
- `Donate` / `DonateCheckout` — Stripe payment flow
- `AdminDashboard` (`/admin`) — generation statistics; requires Firebase sign-in with the admin email; calls `/resume/admin/stats` with a bearer ID token

**API communication:** `src/services/api.ts` wraps all backend calls. CSV data format matches backend's `jobs.csv` schema (columns: `type, company, location, role, start_date, end_date, description`).

**Tests:** vitest specs live in `src/services/__tests__/`.

### Infrastructure
- `backend/docker-compose.yml` — local dev: PostgreSQL (pgvector image), HuggingFace embedding service, backend
- `backend/Dockerfile` — production container (Python 3.13-slim)
- `.github/workflows/deploy-frontend.yml` — GitHub Actions deploys frontend to GitHub Pages on push to `main`
