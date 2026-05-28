# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Frontend (S:/Github/BetterResume/frontend/)
```bash
npm run dev        # Start Vite dev server
npm run build      # Production build
npm run preview    # Preview production build
```

### Backend (S:/Github/BetterResume/backend/)
```bash
# Run API server
uvicorn api.main:app --reload

# Run all tests
pytest

# Run a single test file
pytest tests/test_agent.py

# Run with verbose output
pytest -v tests/

# Docker local dev stack (postgres + embedding service + backend)
docker-compose up
```

## Architecture

BetterResume generates ATS-optimized resumes tailored to job descriptions using LLMs and semantic search.

### Backend: Python FastAPI + LangGraph

**Entry points:**
- `api/main.py` — FastAPI app, CORS, database connection pool lifecycle
- `bot.py` — `Bot` class; orchestrates resume generation via a LangGraph state machine

**Request flow for resume generation:**
1. Frontend POST `/resume/generate` → `api/routers/resume.py`
2. Router instantiates `Bot` and invokes the LangGraph graph
3. `Bot` uses `pg_vector_tool.py` to do semantic search against the user's stored experience/skills in pgvector
4. `llm/gemini_agent.py` calls Google Gemini with retrieved context + job description
5. `resume/writer.py` dispatches to `word_writer.py` or `latex_writer.py` to produce the output file

**Key subsystems:**
- `llm/` — LangChain agent wrappers, LangGraph state (`state.py`), vector search tool
- `resume/` — Format-specific writers (Word, LaTeX), parser, base writer
- `models/` — Pydantic models for `Resume`, `JobExperience`, `Education`, `Skill`
- `utils/db_storage.py` — PostgreSQL interaction (pgvector queries, user data)
- `prompts/` — Plain-text prompt templates loaded at runtime

**Database:** PostgreSQL with pgvector extension. Connection pool managed via `psycopg-pool`. User experience data is stored as vector embeddings for semantic retrieval.

**Required environment variables** (see `.env.template`):
- `GEMINI_API_KEY` — Google Gemini LLM
- `DB_*` — PostgreSQL credentials
- `STRIPE_*` — Stripe payment keys

### Frontend: React 18 + TypeScript + Vite + Tailwind

**Entry points:**
- `src/main.tsx` — React root
- `src/App.tsx` — React Router v7 routes

**Auth:** Firebase authentication via `AuthGate` component wrapping all protected routes. Firebase config lives in `src/services/firebase.ts`.

**Key pages/components:**
- `OnboardingWizard` — multi-step flow to collect user profile and experience
- `EntryBuilder` — UI for building CSV-structured resume entries
- `Home` — main UI triggering resume generation
- `Donate` / `DonateCheckout` — Stripe payment flow

**API communication:** `src/services/api.ts` wraps all backend calls. CSV data format matches backend's `jobs.csv` schema (columns: `type, company, location, role, start_date, end_date, description`).

### Infrastructure
- `backend/docker-compose.yml` — local dev: PostgreSQL (pgvector image), HuggingFace embedding service, backend
- `backend/Dockerfile` — production container (Python 3.13-slim)
- `.github/workflows/deploy-frontend.yml` — GitHub Actions deploys frontend to GitHub Pages on push to `main`
