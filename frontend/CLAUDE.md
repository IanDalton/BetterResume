# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
npm run dev        # Start Vite dev server (http://localhost:5173)
npm run build      # Production build (output: dist/)
npm run preview    # Serve production build locally
```

Set `VITE_API_URL` in a `.env` file to point at the backend (defaults to `http://localhost:8000/resume`).

## Architecture

### Routing (`src/App.tsx`)
React Router v7 with these routes:
- `/` — Home (main resume management UI)
- `/donate` / `/donate-checkout` — Donate page (embedded Stripe checkout)
- `/donate-success` / `/thank-you` — Post-payment pages
- `/admin` — AdminDashboard

### Auth
`AuthGate` component (`src/components/AuthGate.tsx`) wraps all protected routes using Firebase authentication (`src/services/firebase.ts`).

### Key Components (`src/components/`)
- `ProfileEditor` (`components/entries/`) — unified data-entry flow: `PersonalInfoSection`, `ExperienceSection`, `EducationSection`, `LanguagesSection`, `ResumeImportDialog` (resume/LinkedIn-PDF import), `SaveStatusIndicator`
- `ProfilePictureUploader` — profile photo upload with preview
- `FirstLoadGuide` — initial help overlay
- `ThemeToggle` — light/dark mode switch
- `Footer`, `AdBanner`, `DonateToast`, `ErrorBoundary` — supporting chrome
- `components/ui/` — design-system primitives: `Button`, `Input`, `Textarea`, `Select`, `Dialog`, `Card`, `FormField`, `Spinner`, `Stepper`, `Toast`
- `components/admin/` — admin dashboard presentational pieces: `StatCard`, `BarChart`, `CountTable`, `ModelPicker`, `EvalResults.tsx` (exports `ResultsTable`, `RunHistory`, `ModelComparison`); consumed by `pages/AdminDashboard.tsx` and `pages/admin/{StatsTab,ModelsTab,EvalsTab}.tsx` — see Admin Dashboard below

### Admin Dashboard (`src/pages/AdminDashboard.tsx`, `/admin`)
Firebase-gated (admin email allowlist) tab shell over `pages/admin/`:
- `StatsTab` — generation stats (calls `fetchAdminStats` / `exportAdminLogs`)
- `ModelsTab` — per-task model configuration (generation / translation / import / judge) via `ModelPicker` (calls `fetchModelConfig` / `updateModelConfig`). Saving runs a live check on the backend: a model that fails outright is refused with a "Save anyway" escape hatch (`skipCheck`), and one that only works with an unforced tool choice is saved with a notice.
- `EvalsTab` — run evals across models/job descriptions, live-streamed results, run history, and model comparison (calls `fetchEvalFixtures`, `startEvalRun`, `streamEvalRun`, and the `EvalResults.tsx` components' calls)

### Data Types (`src/types.ts`)
```typescript
type EntryType = 'education' | 'certification' | 'job' | 'non-profit' | 'project' | 'contract' | 'part-time'

interface ResumeEntry {
  type: EntryType
  company?: string
  location?: string
  role: string
  start?: string
  end?: string
  description?: string
  role_description?: string
}
```
`EDUCATION_TYPES` / `EXPERIENCE_TYPES` group `EntryType` values by which entry-management section they belong to. Personal info now lives on its own `UserProfile` type (`fullName`, `email`, `phone?`, `address?`, `links: ProfileLink[]`), and languages on `LanguageEntry` — both split out of the old catch-all `entries` array; `legacyMigration.ts` (below) converts old data on load.

### API Service (`src/services/api.ts`)
All backend calls go through this module. Key functions:
- `uploadJobsJson(userId, jobs)` — sync user entries to backend
- `saveProfile(userId, profile)` / `saveLanguages(userId, languages)` — persist personal info / languages
- `generateResume(userId, payload)` — one-shot generation, returns file blob
- `generateResumeStream(userId, payload, onEvent)` — streaming generation with progress callbacks
- `uploadProfilePicture(userId, file)` / `resolveProfilePictureUrl(userId)` — profile image management
- `importResumePdf(userId, file)` — parse an uploaded resume/LinkedIn PDF into profile + entries
- `fetchAdminStats(idToken, days)` / `exportAdminLogs(idToken)` — admin generation stats and log export
- `fetchOpenRouterModels(...)` / `fetchModelConfig(idToken)` / `updateModelConfig(idToken, ..., skipCheck?)` / `checkModel(idToken, model)` — OpenRouter model catalog, per-task model configuration, and the live model compatibility check
- `fetchEvalFixtures(...)`, `startEvalRun(idToken, payload)`, `streamEvalRun(idToken, runId, onCell)`, `fetchEvalRuns(idToken)`, `fetchEvalRun(idToken, runId)`, `fetchEvalComparison(idToken)`, `downloadEvalResume(idToken, resultId, format)` — eval subsystem

`ResumeRequestPayload`: `{ job_description, format, include_profile_picture? }` — no `model` field; the backend resolves the model per task from runtime config, not from the request.

### Other Services
- `src/services/firebase.ts` — Firebase auth & Firestore config
- `src/services/csv.ts` — serialize/deserialize `ResumeEntry[]` to CSV (matches backend `jobs.csv` column order)
- `src/services/stripe.ts` — Stripe.js initialization
- `src/services/analytics.ts` — event tracking
- `src/services/geolocation.ts` — IP-based country detection
- `src/services/legacyMigration.ts` — splits the old mixed `entries` shape (profile/languages encoded as typed rows) into `UserProfile` / `LanguageEntry[]` / `ResumeEntry[]`, mirroring the backend's one-time DB migration
- `src/services/resumeImport.ts` — maps a parsed resume-import entry onto `ResumeEntry`
- `src/services/index.ts` — barrel re-export of `api.ts` and `csv.ts`

### Build (`vite.config.ts`)
Manual chunk splitting keeps bundle sizes manageable:
- `react` vendor chunk — React + React-DOM
- `firebase` chunk — Firebase SDK (large; split to avoid blocking initial load)
- Chunk size warning threshold: 800 KB

### Deployment
GitHub Actions (`.github/workflows/deploy-frontend.yml`) builds and publishes `dist/` to GitHub Pages on every push to `main`.
