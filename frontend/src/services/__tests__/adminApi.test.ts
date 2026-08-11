import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  fetchOpenRouterModels,
  fetchModelConfig,
  updateModelConfig,
  startEvalRun,
  fetchEvalRuns,
  downloadEvalResume,
} from '../api';

const TOKEN = 'fake-id-token';

function mockFetch(response: Partial<Response>) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, ...response });
  vi.stubGlobal('fetch', fn);
  return fn;
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe('admin model API', () => {
  it('requests tool-capable models by default and sends the bearer token', async () => {
    const fetchMock = mockFetch({ json: async () => ({ models: [{ id: 'a/b' }] }) });
    const models = await fetchOpenRouterModels(TOKEN);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/admin/models');
    expect(url).toContain('tools_only=true');
    expect(init.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(models).toHaveLength(1);
  });

  it('passes the search query and show-all flag', async () => {
    const fetchMock = mockFetch({ json: async () => ({ models: [] }) });
    await fetchOpenRouterModels(TOKEN, { toolsOnly: false, q: 'qwen' });
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain('tools_only=false');
    expect(url).toContain('q=qwen');
  });

  it('throws forbidden on 403', async () => {
    mockFetch({ ok: false, status: 403 });
    await expect(fetchOpenRouterModels(TOKEN)).rejects.toThrow('forbidden');
  });

  it('surfaces the backend detail message on 503', async () => {
    mockFetch({ ok: false, status: 503, json: async () => ({ detail: 'OpenRouter model list unavailable: down' }) });
    await expect(fetchOpenRouterModels(TOKEN)).rejects.toThrow(/unavailable/);
  });

  it('reads the model config', async () => {
    mockFetch({ json: async () => ({ tasks: { generation: { primary: 'openrouter:a', fallback: null } } }) });
    const cfg = await fetchModelConfig(TOKEN);
    expect(cfg.tasks.generation.primary).toBe('openrouter:a');
  });

  it('PUTs a model config update', async () => {
    const fetchMock = mockFetch({ json: async () => ({ tasks: {} }) });
    await updateModelConfig(TOKEN, 'generation', 'openrouter:new', 'google-gla:fb');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/admin/model-config');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({
      task: 'generation', primary: 'openrouter:new', fallback: 'google-gla:fb',
    });
  });
});

describe('admin eval API', () => {
  it('POSTs a run and returns the id', async () => {
    mockFetch({ status: 202, json: async () => ({ run_id: 'run-1' }) });
    const { run_id } = await startEvalRun(TOKEN, {
      models: ['openrouter:a'], jd_ids: ['senior_swe'], custom_jd: null,
      data_source: 'fixture', judge_model: 'google-gla:j', notes: null,
    });
    expect(run_id).toBe('run-1');
  });

  it('surfaces a 400 spec error message', async () => {
    mockFetch({ ok: false, status: 400, json: async () => ({ detail: 'At most 5 models per run' }) });
    await expect(startEvalRun(TOKEN, {
      models: [], jd_ids: [], custom_jd: null, data_source: 'fixture', judge_model: null, notes: null,
    })).rejects.toThrow('At most 5 models per run');
  });

  it('lists runs', async () => {
    mockFetch({ json: async () => ({ runs: [{ id: 'run-1' }] }) });
    expect(await fetchEvalRuns(TOKEN)).toHaveLength(1);
  });

  it('downloads a resume blob with the requested format', async () => {
    const blob = new Blob(['x']);
    const fetchMock = mockFetch({ blob: async () => blob });
    await downloadEvalResume(TOKEN, 'result-1', 'word');
    expect(fetchMock.mock.calls[0][0]).toContain('format=word');
  });
});
