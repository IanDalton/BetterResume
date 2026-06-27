import { afterEach, describe, expect, it, vi } from 'vitest';
import { API_BASE, fetchAdminStats, exportAdminLogs } from '../api';

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
