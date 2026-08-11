# Manual verification checklist — admin model management & evals

Everything on this branch is covered by automated tests **except** what needs a
browser, a live database, or real provider credentials. This project has no
frontend component-test setup, so all UI work was verified by build, type-check
and code review. The list below is what a human still needs to click through.

Run `docker-compose up` in `backend/` and `npm run dev` in `frontend/`, then
sign in at `/admin` with the admin account.

## 1. The production fix (highest priority)

- [ ] Generate a resume normally. Confirm it succeeds and a `generation_events`
      row appears with `requested_model` populated and `fallback_used = false`.
- [ ] **Model change takes effect on a repeat generation.** Generate for a job
      description, then change the generation model in Models, then regenerate
      the *same* job description with an unchanged entries list. The output must
      differ and a new `generation_events` row must appear. (This is the path a
      final-review Critical was fixed on — the cache used to serve the old
      model's resume here.)
- [ ] **Fallback actually fires.** Set the generation primary to a model with no
      tool support and the fallback to `google-gla:gemini-2.5-flash-lite`.
      Generate. The user should still get a resume; the dashboard's fallback-rate
      card should become non-zero and the event should record both models.
- [ ] Confirm `GENERATION_FALLBACK_MODEL` defaulting to Gemini Flash Lite is an
      acceptable cost/quota change — primary failures now consume that key where
      they previously just errored.

## 2. Models tab

- [ ] All three cards load with real values and an "Updated … by …" footer.
- [ ] Picker search is debounced (not one request per keystroke); tool-capable
      only by default; unchecking shows non-tool models with the amber warning.
- [ ] A saved choice survives a page reload.
- [ ] **Catalog outage path:** block outbound access to `openrouter.ai`, reopen
      the picker, and confirm the free-text field still works. Losing this would
      leave you unable to change models exactly when you need to.
- [ ] A failed save (stop the backend mid-request) shows a red error and leaves
      the previous model on screen rather than blanking the card.

## 3. Evals tab

- [ ] Fixture JDs load; the cost line updates live; exceeding 5 models or 20
      cells disables Run with the cap hint.
- [ ] Selecting fixture JDs disables the custom-JD box and vice versa.
- [ ] Start a run with two cheap models against one JD. Cells must fill in
      **independently as they land**, not all at once — this is the only way to
      confirm the SSE stream end to end.
- [ ] Force one model to fail. Its cell shows ERROR, and **expanding that row
      must not crash the page** (this was a Critical caught in review).
- [ ] When the run finishes, the live grid switches to the sortable results
      table. Column headers sort and toggle direction.
- [ ] Expand a successful row: judge reasoning, missing-keyword chips, and a
      *readable* resume — title, summary, experience with bullets, skills,
      education — not raw JSON.
- [ ] Download Word and LaTeX. Both download and open. **Neither returns a PDF**
      — that is existing writer behaviour, not a regression.
- [ ] "Promote to active" shows the confirm dialog, updates the Models tab's
      generation primary, and **leaves the fallback unchanged**.
- [ ] History lists the run after a reload with the right status chip; Compare
      aggregates across runs.

## 4. Operational

- [ ] Restart the backend mid-run; the run is marked `interrupted`, not left
      `running`.
- [ ] Check both light and dark mode across the new tabs.
- [ ] If you ever run uvicorn with `--workers > 1`, note that `_EVAL_STREAMS` is
      per-process: a `/stream` request landing on a different worker than the
      `POST` will 404. The shipped Dockerfile is single-process, so this is only
      a scaling concern.
