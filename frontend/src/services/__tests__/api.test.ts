import { afterEach, describe, expect, it, vi } from 'vitest';
import { API_BASE, analyzeResume, analyzeResumePdf, fetchAdminStats, exportAdminLogs } from '../api';

const SAMPLE = {
  totals: { users: 1, resume_requests: 2, requesting_users: 1, generations: 2, successful_generations: 2, success_rate: 1, avg_duration_ms: 1000 },
  generations_per_day: [],
  requests_per_day: [],
  by_model: [],
  by_format: [],
  by_language: [],
  top_users: [],
  recent_requests: [],
  donations: { by_currency: [] },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fetchAdminStats', () => {
  it('sends the bearer token and days param', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => SAMPLE });
    vi.stubGlobal('fetch', fetchMock);

    const stats = await fetchAdminStats('tok123', 7);

    expect(stats).toEqual(SAMPLE);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/admin/stats?days=7`,
      { headers: { Authorization: 'Bearer tok123' } },
    );
  });

  it('throws forbidden on 401/403', async () => {
    for (const status of [401, 403]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status, json: async () => ({}) }));
      await expect(fetchAdminStats('tok')).rejects.toThrow('forbidden');
    }
  });

  it('throws on other failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));
    await expect(fetchAdminStats('tok')).rejects.toThrow('Stats request failed: 500');
  });
});

describe('exportAdminLogs', () => {
  it('sends the bearer token and returns a blob', async () => {
    const blob = new Blob(['id,status\n1,error'], { type: 'text/csv' });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, blob: async () => blob });
    vi.stubGlobal('fetch', fetchMock);

    const result = await exportAdminLogs('tok123');

    expect(result).toBe(blob);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/admin/logs/export`,
      { headers: { Authorization: 'Bearer tok123' } },
    );
  });

  it('throws forbidden on 401/403', async () => {
    for (const status of [401, 403]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status, blob: async () => new Blob() }));
      await expect(exportAdminLogs('tok')).rejects.toThrow('forbidden');
    }
  });
});

describe('analyzeResume', () => {
  const RESUME = { language: 'en', resume_section: { title: 'Engineer' } };
  const ANALYSIS = {
    ats: { score: 72, keyword_coverage: 60, matched_keywords: ['Python'], missing_keywords: ['Go'], issues: [] },
    review: null,
    review_error: 'judge down',
    model: null,
  };

  it('posts the job description, resume and language', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ANALYSIS });
    vi.stubGlobal('fetch', fetchMock);

    const result = await analyzeResume('user 1', { job_description: 'jd', resume: RESUME, language: 'es' });

    expect(result).toEqual(ANALYSIS);
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/analyze-resume/user%201`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_description: 'jd', resume: RESUME, language: 'es' }),
    });
  });

  it('surfaces the backend detail on failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'Invalid resume payload' }) }));
    await expect(analyzeResume('user1', { job_description: 'jd', resume: RESUME })).rejects.toThrow('Invalid resume payload');
  });

  it('falls back to a status message when there is no detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));
    await expect(analyzeResume('user1', { job_description: 'jd', resume: RESUME })).rejects.toThrow('Analysis failed: 500');
  });
});

describe('analyzeResumePdf', () => {
  it('posts the file, job description and language as multipart form data', async () => {
    const body = { ats: { score: 40 }, review: null, review_error: null, model: null, resume: {}, warnings: ['w'] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => body });
    vi.stubGlobal('fetch', fetchMock);
    const file = new File([new Uint8Array([37, 80, 68, 70])], 'cv.pdf', { type: 'application/pdf' });

    const result = await analyzeResumePdf('user1', file, 'Senior Python', 'es');

    expect(result).toEqual(body);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE}/analyze-resume-pdf/user1`);
    expect(init.method).toBe('POST');
    const form = init.body as FormData;
    expect(form.get('file')).toBe(file);
    expect(form.get('job_description')).toBe('Senior Python');
    expect(form.get('language')).toBe('es');
  });

  it('surfaces the backend detail on failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: 'No work experience was found' }) }));
    const file = new File(['x'], 'cv.pdf', { type: 'application/pdf' });
    await expect(analyzeResumePdf('user1', file, 'jd')).rejects.toThrow('No work experience was found');
  });
});
