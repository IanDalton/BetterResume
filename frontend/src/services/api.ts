import type { LanguageEntry, ProfileLink, UserProfile } from '../types';

const API_BASE_RAW = import.meta.env.VITE_API_URL || 'http://localhost:8000/resume';
const API_BASE = API_BASE_RAW.replace(/\/+$/, '').replace(/\/resume$/, '') + '/resume';

export { API_BASE };

async function _jsonOrThrow(res: Response, failureLabel: string) {
  if (!res.ok) {
    let message = `${failureLabel}: ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) message = data.detail;
    } catch { }
    throw new Error(message);
  }
  return res.json();
}

export async function saveProfile(userId: string, profile: UserProfile): Promise<void> {
  const res = await fetch(`${API_BASE}/profile/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      full_name: profile.fullName || null,
      email: profile.email || null,
      phone: profile.phone || null,
      address: profile.address || null,
      links: profile.links,
    }),
  });
  await _jsonOrThrow(res, 'Failed to save profile');
}

export async function saveLanguages(userId: string, languages: LanguageEntry[]): Promise<void> {
  const res = await fetch(`${API_BASE}/languages/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ languages }),
  });
  await _jsonOrThrow(res, 'Failed to save languages');
}

interface ResumeRequestPayload {
  job_description: string;
  format: string;
  include_profile_picture?: boolean;
}

export async function uploadJobsJson(userId: string, jobs: Array<{ type: string; company: string; description: string; role?: string; location?: string; start_date?: string; end_date?: string }>) {
  const res = await fetch(`${API_BASE}/upload-jobs/${encodeURIComponent(userId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jobs })
  });
  if (!res.ok) {
    let message = `Upload failed: ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) message = data.detail;
    } catch { }
    throw new Error(message);
  }
  return res.json();
}

export async function generateResume(userId: string, payload: ResumeRequestPayload) {
  const res = await fetch(`${API_BASE}/generate-resume/${encodeURIComponent(userId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw new Error(`Generate failed: ${res.status}`);
  const data = await res.json() as { result: any; files: { pdf: string; source: string } };
  if (data.files) {
    const fix = (p: string) => {
      if (!p) return p;
      if (p.startsWith('http')) return p;
      // If already has /download/ assume correct relative path
      if (p.includes('/download/')) return API_BASE.replace(/\/$/, '') + p;
      // Bare filename -> construct
      return API_BASE.replace(/\/$/, '') + `/download/${encodeURIComponent(userId)}/${p}`;
    };
    data.files = { pdf: fix(data.files.pdf), source: fix(data.files.source) };
  }
  return data;
}

/** One Server-Sent Events frame: the optional `event:` line's value, and the
 * parsed JSON payload of its `data:` line (or `undefined` if the frame had
 * no parseable `data:` line). */
interface SseFrame {
  event: string | null;
  data: any;
}

/** Reads an SSE response body, splitting it into frames on the blank-line
 * separator and invoking `onFrame` with each as it completes. Shared by
 * `generateResumeStream` and `streamEvalRun` so the chunk-buffering /
 * frame-splitting logic (and `event:`/`data:` line parsing) lives in one
 * place rather than being duplicated per stream consumer. */
function pumpSseBody(body: ReadableStream<Uint8Array>, onFrame: (frame: SseFrame) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  function parseFrame(raw: string): SseFrame | null {
    let event: string | null = null;
    let data: any = undefined;
    let sawData = false;
    for (const rawLine of raw.split('\n')) {
      const line = rawLine.trim();
      if (line.startsWith('event:')) {
        event = line.slice('event:'.length).trim();
      } else if (line.startsWith('data:')) {
        sawData = true;
        try {
          data = JSON.parse(line.slice('data:'.length).trim());
        } catch { /* ignore malformed data lines */ }
      }
    }
    if (!sawData && event === null) return null;
    return { event, data };
  }

  function pump(): Promise<void> {
    return reader.read().then(({ done, value }) => {
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      for (let i = 0; i < parts.length - 1; i++) {
        const frame = parseFrame(parts[i]);
        if (frame) onFrame(frame);
      }
      buffer = parts[parts.length - 1];
      return pump();
    });
  }
  return pump();
}

export function generateResumeStream(userId: string, payload: ResumeRequestPayload, onEvent: (evt: any) => void): Promise<{ result: any; files?: { pdf: string; source: string } }> {
  // Returns a promise resolving to final result while invoking onEvent per progress event.
  return new Promise((resolve, reject) => {
    // We POST first to initiate SSE because EventSource only supports GET natively; we fallback to fetch+ReadableStream poly.
    // Simpler approach: create a fetch POST to the stream endpoint and manually parse SSE lines.
    fetch(`${API_BASE}/generate-resume-stream/${encodeURIComponent(userId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(res => {
      if (!res.ok || !res.body) { reject(new Error(`Stream failed: ${res.status}`)); return; }
      pumpSseBody(res.body, ({ data: json }) => {
        if (json === undefined) return;
        onEvent(json);
        if (json.stage === 'done') {
          // Normalize relative file links to absolute
          let files = json.files;
          if (files) {
            const toAbs = (p: string) => {
              if (!p) return p;
              if (p.startsWith('http')) return p;
              if (p.includes('/download/')) return API_BASE.replace(/\/$/, '') + p; // relative download path
              // bare filename
              return API_BASE.replace(/\/$/, '') + `/download/${encodeURIComponent(userId)}/${p}`;
            };
            files = { pdf: toAbs(files.pdf), source: toAbs(files.source) };
          }
          resolve({ result: json.result, files });
        } else if (json.stage === 'error') {
          reject(new Error(json.message || 'Error'));
        }
      }).catch(err => reject(err));
    }).catch(err => reject(err));
  });
}

export interface AdminStats {
  totals: {
    users: number;
    resume_requests: number;
    requesting_users: number;
    generations: number;
    successful_generations: number;
    success_rate: number | null;
    avg_duration_ms: number;
    fallback_generations: number;
    fallback_rate: number | null;
  };
  generations_per_day: Array<{ day: string; count: number }>;
  requests_per_day: Array<{ day: string; count: number }>;
  requests_by_hour: Array<{ hour: number; count: number }>;
  requests_by_weekday: Array<{ weekday: number; count: number }>;
  user_request_distribution: Array<{ bucket: string; count: number }>;
  by_model: Array<{ model: string; count: number }>;
  by_format: Array<{ format: string; count: number }>;
  by_language: Array<{ language: string; count: number }>;
  by_status: Array<{ status: string; count: number }>;
  duration_percentiles: { p50_ms: number | null; p95_ms: number | null };
  top_keywords: Array<{ term: string; count: number }>;
  top_users: Array<{ user_id: string; requests: number; last_request: string }>;
  recent_requests: Array<{ user_id: string; job_posting_preview: string; created_at: string }>;
  recent_errors: Array<{ created_at: string; user_id: string; model: string; format: string; status: string; error: string }>;
  donations: { by_currency: Array<{ currency: string; count: number; total_amount: number }> };
}

export async function fetchAdminStats(idToken: string, days = 30): Promise<AdminStats> {
  const res = await fetch(`${API_BASE}/admin/stats?days=${days}`, {
    headers: { Authorization: `Bearer ${idToken}` }
  });
  if (res.status === 401 || res.status === 403) {
    throw new Error('forbidden');
  }
  if (!res.ok) throw new Error(`Stats request failed: ${res.status}`);
  return res.json();
}

export async function exportAdminLogs(idToken: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}/admin/logs/export`, {
    headers: { Authorization: `Bearer ${idToken}` }
  });
  if (res.status === 401 || res.status === 403) {
    throw new Error('forbidden');
  }
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  return res.blob();
}

/** Shared fetch wrapper for the newer `/admin/*` endpoints (model catalog,
 * model config, evals): attaches the bearer token, normalizes 401/403 into
 * `Error('forbidden')` (matching `fetchAdminStats`/`exportAdminLogs` above),
 * and surfaces the backend's `detail` message on any other non-OK response. */
async function adminRequest(idToken: string, path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${idToken}`, ...(init.headers || {}) },
  });
  if (res.status === 401 || res.status === 403) throw new Error('forbidden');
  if (!res.ok) {
    let message = `Request failed: ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) message = data.detail;
    } catch { }
    throw new Error(message);
  }
  return res;
}

export interface CatalogModel {
  id: string;
  model_string: string;
  name: string;
  context_length: number | null;
  prompt_price: number | null;
  completion_price: number | null;
  supports_tools: boolean;
  supports_structured_outputs: boolean;
}

export interface TaskModelConfig {
  primary: string;
  fallback: string | null;
  // The judge runs one standalone scoring call, so it has no fallback slot.
  supports_fallback: boolean;
  updated_at: string | null;
  updated_by: string | null;
}

export type ModelTask = 'generation' | 'translation' | 'import' | 'judge';

export interface ModelConfigResponse {
  tasks: Record<ModelTask, TaskModelConfig>;
  // Set by a save whose model passed its live check with a caveat -- currently
  // only "this model rejects forced tool calls, so we ask instead".
  notice?: string | null;
}

export interface ModelComparisonRow {
  model: string;
  runs: number;
  cells: number;
  success_rate: number | null;
  avg_composite: number | null;
  avg_schema: number | null;
  avg_ats: number | null;
  avg_judge: number | null;
  avg_duration_ms: number | null;
  last_run_at: string | null;
}

export interface EvalRun {
  id: string;
  created_at: string;
  finished_at: string | null;
  created_by: string | null;
  status: string;
  data_source: string;
  judge_model: string | null;
  models: string[];
  jd_ids: string[];
  custom_jd: string | null;
  notes: string | null;
}

export interface EvalResult {
  id: string;
  run_id: string;
  model: string;
  jd_id: string | null;
  status: string;
  error: string | null;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  fallback_used: boolean;
  // Every field below this line is seeded `None` for an errored cell (see
  // backend/evals/runner.py `_run_cell`'s `result` dict, lines ~122-138) and
  // only ever gets filled in on the success path -- an error cell arrives
  // over the wire with all of these as `null`, never `[]` or `0`. Do not
  // widen any of these back to a non-nullable type without re-auditing every
  // place that reads it.
  schema_score: number | null;
  schema_passed: boolean | null;
  schema_errors: string[] | null;
  ats_score: number | null;
  ats_coverage: number | null;
  missing_keywords: string[] | null;
  judge_overall: number | null;
  judge_relevance: number | null;
  judge_quality: number | null;
  judge_coherence: number | null;
  judge_reasoning: string | null;
  composite_score: number | null;
  resume_json: any;
}

/** Body of `POST /admin/evals`: the spec for a new evaluation run. */
export interface EvalRunRequest {
  models: string[];
  jd_ids: string[];
  custom_jd: string | null;
  data_source: string;
  judge_model: string | null;
  notes: string | null;
}

export async function fetchOpenRouterModels(
  idToken: string,
  opts: { toolsOnly?: boolean; q?: string } = {}
): Promise<CatalogModel[]> {
  const params = new URLSearchParams({ tools_only: String(opts.toolsOnly ?? true) });
  if (opts.q) params.set('q', opts.q);
  const res = await adminRequest(idToken, `/admin/models?${params}`);
  return (await res.json()).models;
}

export async function fetchModelConfig(idToken: string): Promise<ModelConfigResponse> {
  const res = await adminRequest(idToken, '/admin/model-config');
  return res.json();
}

export async function updateModelConfig(
  idToken: string, task: ModelTask, primary: string, fallback: string | null,
  // The backend runs one live request against the model before storing it, so a
  // model that cannot serve our request shape is rejected here rather than on a
  // user's generation. Pass true to store it regardless.
  skipCheck = false
): Promise<ModelConfigResponse> {
  const res = await adminRequest(idToken, '/admin/model-config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task, primary, fallback, skip_check: skipCheck }),
  });
  return res.json();
}

export interface ModelCheckResult {
  model: string;
  ok: boolean;
  detail: string | null;
  // False when the model only works with an unforced tool choice; still usable.
  forced_tool_choice: boolean;
  message: string;
}

export async function checkModel(idToken: string, model: string): Promise<ModelCheckResult> {
  const res = await adminRequest(idToken, '/admin/model-check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model }),
  });
  return res.json();
}

export async function fetchEvalFixtures(
  idToken: string
): Promise<{ job_descriptions: Array<{ id: string; label: string; preview: string }>; default_judge_model: string }> {
  const res = await adminRequest(idToken, '/admin/evals/fixtures');
  return res.json();
}

export async function startEvalRun(idToken: string, payload: EvalRunRequest): Promise<{ run_id: string }> {
  const res = await adminRequest(idToken, '/admin/evals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return res.json();
}

/** Streams live results for an in-flight eval run via SSE, invoking `onCell`
 * for each `event: cell` frame. Uses `fetch` (not `EventSource`) because the
 * endpoint requires an `Authorization: Bearer` header, which `EventSource`
 * cannot send. Resolves once the backend closes the stream (it does so right
 * after emitting `event: done`); rejects if the backend instead reports
 * `event: error` (the run itself failed) or the connection fails. */
export async function streamEvalRun(idToken: string, runId: string, onCell: (r: EvalResult) => void): Promise<void> {
  const res = await fetch(`${API_BASE}/admin/evals/${encodeURIComponent(runId)}/stream`, {
    headers: { Authorization: `Bearer ${idToken}` },
  });
  if (res.status === 401 || res.status === 403) throw new Error('forbidden');
  if (!res.ok || !res.body) throw new Error(`Stream failed: ${res.status}`);

  let runError: Error | null = null;
  await pumpSseBody(res.body, ({ event, data }) => {
    if (event === 'cell') {
      if (data !== undefined) onCell(data as EvalResult);
    } else if (event === 'error') {
      runError = new Error(data?.message || 'Eval run failed');
    }
    // 'done' carries no payload of interest -- the backend closes the stream
    // right after it, which ends pumpSseBody's read loop on its own.
  });
  if (runError) throw runError;
}

export async function fetchEvalRuns(idToken: string): Promise<EvalRun[]> {
  const res = await adminRequest(idToken, '/admin/evals');
  return (await res.json()).runs;
}

export async function fetchEvalRun(idToken: string, runId: string): Promise<{ run: EvalRun; results: EvalResult[] }> {
  const res = await adminRequest(idToken, `/admin/evals/${encodeURIComponent(runId)}`);
  return res.json();
}

export async function fetchEvalComparison(idToken: string): Promise<ModelComparisonRow[]> {
  const res = await adminRequest(idToken, '/admin/evals/compare');
  return (await res.json()).models;
}

export async function downloadEvalResume(idToken: string, resultId: string, format: string): Promise<Blob> {
  const res = await adminRequest(idToken, `/admin/evals/results/${encodeURIComponent(resultId)}/download?format=${encodeURIComponent(format)}`);
  return res.blob();
}

export async function uploadProfilePicture(userId: string, file: File) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/upload-profile-picture/${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: form
  });
  if (!res.ok) {
    let message = `Upload failed: ${res.status}`;
    try {
      const data = await res.json();
      if (data?.detail) message = data.detail;
    } catch {
      const text = await res.text().catch(() => '');
      if (text) message = text;
    }
    throw new Error(message);
  }
  return res.json();
}

export interface ResumeImportProfile {
  full_name?: string | null;
  headline?: string | null;
  summary?: string | null;
  location?: string | null;
  email?: string | null;
  phone?: string | null;
  links: ProfileLink[];
}

export interface ResumeImportEntry {
  type: string;
  company: string;
  description: string;
  role?: string | null;
  location?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface ResumeImportResult {
  profile: ResumeImportProfile;
  experience: ResumeImportEntry[];
  education: ResumeImportEntry[];
  skills: string[];
  languages: LanguageEntry[];
  warnings: string[];
}

/** Uploads a resume PDF (any resume/CV, including a LinkedIn "Save to PDF"
 * export) for parsing. Nothing is saved server-side by this call -- the
 * result is for the user to review before anything is merged into their
 * profile/entries (see legacyMigration-style adapter in
 * services/resumeImport.ts). */
export async function importResumePdf(userId: string, file: File): Promise<ResumeImportResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/import/resume/${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: form,
  });
  return _jsonOrThrow(res, 'Import failed');
}

export async function resolveProfilePictureUrl(userId: string): Promise<string | null> {
  const cacheBuster = Date.now();
  const url = `${API_BASE}/profile-picture/${encodeURIComponent(userId)}?v=${cacheBuster}`;
  try {
    const res = await fetch(url, { method: 'HEAD' });
    if (res.ok) return url;
    if (res.status === 405) {
      const getRes = await fetch(url, { method: 'GET' });
      if (!getRes.ok) return null;
      // Consume body to avoid locking resources
      try { await getRes.arrayBuffer(); } catch { }
      return url;
    }
    return null;
  } catch {
    return null;
  }
}
