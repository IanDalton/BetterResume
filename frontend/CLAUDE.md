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
- `/donate` — Donate page
- `/donate-checkout` — Stripe Elements checkout
- `/donate-success` / `/thank-you` — Post-payment pages

### Auth
`AuthGate` component (`src/components/AuthGate.tsx`) wraps all protected routes using Firebase authentication (`src/services/firebase.ts`).

### Key Components (`src/components/`)
- `OnboardingWizard` — multi-step first-run flow to collect user profile and experience
- `EntryBuilder` — form for creating/editing resume entries
- `JobsTable` — table view of all resume entries with edit/delete
- `JobForm` — individual entry form (used inside EntryBuilder)
- `ProfilePictureUploader` — profile photo upload with preview
- `DonateCheckout` — Stripe Elements payment form
- `FirstLoadGuide` — initial help overlay
- `ThemeToggle` — light/dark mode switch

### Data Types (`src/types.ts`)
```typescript
type EntryType = 'info' | 'education' | 'certification' | 'job' | 'non-profit' | 'project' | 'contract' | 'part-time'

interface ResumeEntry {
  type: EntryType
  company: string
  location: string
  role: string
  start: string
  end: string
  description: string
  role_description: string
}
```
`isWorkLike(type)` helper classifies entries that represent work experience.

### API Service (`src/services/api.ts`)
All backend calls go through this module. Key functions:
- `uploadJobsJson(userId, jobs)` — sync user entries to backend
- `generateResume(userId, payload)` — one-shot generation, returns file blob
- `generateResumeStream(userId, payload, onEvent)` — streaming generation with progress callbacks
- `uploadProfilePicture(userId, file)` / `resolveProfilePictureUrl(userId)` — profile image management

`ResumeRequestPayload`: `{ job_description, format, model, include_profile_picture }`

### Other Services
- `src/services/firebase.ts` — Firebase auth & Firestore config
- `src/services/csv.ts` — serialize/deserialize `ResumeEntry[]` to CSV (matches backend `jobs.csv` column order)
- `src/services/stripe.ts` — Stripe.js initialization
- `src/services/analytics.ts` — event tracking

### Build (`vite.config.ts`)
Manual chunk splitting keeps bundle sizes manageable:
- `react` vendor chunk — React + React-DOM
- `firebase` chunk — Firebase SDK (large; split to avoid blocking initial load)
- Chunk size warning threshold: 800 KB

### Deployment
GitHub Actions (`.github/workflows/deploy-frontend.yml`) builds and publishes `dist/` to GitHub Pages on every push to `main`.
