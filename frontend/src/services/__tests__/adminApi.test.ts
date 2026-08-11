import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  fetchOpenRouterModels,
  fetchModelConfig,
  updateModelConfig,
  checkModels,
  startEvalRun,
  fetchEvalRuns,
  downloadEvalResume,
  streamEvalRun,
  generateResumeStream,
  API_BASE,
} from '../api';

const TOKEN = 'fake-id-token';

function mockFetch(response: Partial<Response>) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, ...response });
  vi.stubGlobal('fetch', fn);
  return fn;
}

/** Builds a `ReadableStream<Uint8Array>` that yields the given string chunks
 * one `pull()` at a time, so tests can control exactly how bytes arrive --
 * including splitting a single SSE frame across two `reader.read()` calls,
 * which is the case that byte-buffering logic most commonly gets wrong. */
function chunksToStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i]));
        i += 1;
      } else {
        controller.close();
      }
    },
  });
}

function mockStreamFetch(chunks: string[], responseOverrides: Partial<Response> = {}) {
  const fn = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: chunksToStream(chunks),
    ...responseOverrides,
  });
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
    await updateModelConfig(TOKEN, 'generation', 'openrouter:new', 'openrouter:fb');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/admin/model-config');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({
      task: 'generation', primary: 'openrouter:new', fallback: 'openrouter:fb', skip_check: false,
    });
  });

  it('can PUT a model config update that skips the live check', async () => {
    const fetchMock = mockFetch({ json: async () => ({ tasks: {} }) });
    await updateModelConfig(TOKEN, 'judge', 'openrouter:new', null, true);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).skip_check).toBe(true);
  });

  it('surfaces the reason a model config update was refused', async () => {
    mockFetch({
      ok: false, status: 400,
      json: async () => ({ detail: "openrouter:qwen/qwen3.7-flash failed a live check and was not saved: No endpoints found that support the provided 'tool_choice' value" }),
    });
    await expect(updateModelConfig(TOKEN, 'generation', 'openrouter:qwen/qwen3.7-flash', null))
      .rejects.toThrow(/failed a live check/);
  });

  it('POSTs a model check for every model at once', async () => {
    const fetchMock = mockFetch({
      json: async () => ({ results: [
        { model: 'openrouter:a', ok: true, detail: null, forced_tool_choice: true, reasoning_disabled: true, message: 'Model responded correctly' },
        { model: 'openrouter:b', ok: false, detail: 'boom', forced_tool_choice: true, reasoning_disabled: true, message: 'boom' },
      ] }),
    });
    const results = await checkModels(TOKEN, ['openrouter:a', 'openrouter:b']);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/admin/model-check');
    expect(JSON.parse(init.body)).toEqual({ models: ['openrouter:a', 'openrouter:b'] });
    expect(results.map(r => r.ok)).toEqual([true, false]);
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

describe('streamEvalRun', () => {
  it('invokes onCell once per cell frame, in order, and resolves when the stream closes', async () => {
    mockStreamFetch([
      `event: cell\ndata: ${JSON.stringify({ id: 'c1', model: 'm/a' })}\n\n`,
      `event: cell\ndata: ${JSON.stringify({ id: 'c2', model: 'm/b' })}\n\n`,
      'event: done\ndata: {}\n\n',
    ]);
    const onCell = vi.fn();

    await expect(streamEvalRun(TOKEN, 'run-1', onCell)).resolves.toBeUndefined();

    expect(onCell).toHaveBeenCalledTimes(2);
    expect(onCell.mock.calls[0][0]).toEqual({ id: 'c1', model: 'm/a' });
    expect(onCell.mock.calls[1][0]).toEqual({ id: 'c2', model: 'm/b' });
  });

  it('surfaces an error frame to the caller instead of swallowing it', async () => {
    mockStreamFetch([
      'event: error\ndata: {"message":"OpenRouter timed out"}\n\n',
      'event: done\ndata: {}\n\n',
    ]);
    const onCell = vi.fn();

    await expect(streamEvalRun(TOKEN, 'run-1', onCell)).rejects.toThrow('OpenRouter timed out');
    expect(onCell).not.toHaveBeenCalled();
  });

  it('reassembles a cell frame whose data line is split across chunk boundaries', async () => {
    const frame = `event: cell\ndata: ${JSON.stringify({ id: 'c1', model: 'm/a', note: 'split across reads' })}\n\n`;
    const splitAt = frame.indexOf('"note"'); // land the split mid-JSON, mid-data-line
    const chunks = [
      frame.slice(0, splitAt),
      frame.slice(splitAt) + 'event: done\ndata: {}\n\n',
    ];
    mockStreamFetch(chunks);
    const onCell = vi.fn();

    await streamEvalRun(TOKEN, 'run-1', onCell);

    // Must fire exactly once with the fully-reassembled object -- not dropped
    // (never fires), not double-emitted (fires once per partial read), and
    // not corrupted (a JSON.parse of a half-arrived line would throw and be
    // silently swallowed by the frame parser's own try/catch).
    expect(onCell).toHaveBeenCalledTimes(1);
    expect(onCell).toHaveBeenCalledWith({ id: 'c1', model: 'm/a', note: 'split across reads' });
  });

  it('throws when no in-flight run has that id (404)', async () => {
    mockFetch({ ok: false, status: 404 });
    await expect(streamEvalRun(TOKEN, 'missing-run', vi.fn())).rejects.toThrow('404');
  });
});

describe('generateResumeStream (regression: unnamed-frame SSE path)', () => {
  it('invokes onEvent for plain data-only frames and resolves with the final result', async () => {
    mockStreamFetch([
      `data: ${JSON.stringify({ stage: 'progress', message: 'searching experience' })}\n\n`,
      `data: ${JSON.stringify({
        stage: 'done',
        result: { ok: true },
        files: { pdf: 'resume.pdf', source: 'resume.docx' },
      })}\n\n`,
    ]);
    const onEvent = vi.fn();

    const result = await generateResumeStream(
      'user-1',
      { job_description: 'jd text', format: 'word' },
      onEvent,
    );

    expect(onEvent).toHaveBeenCalledTimes(2);
    expect(onEvent.mock.calls[0][0]).toEqual({ stage: 'progress', message: 'searching experience' });
    expect(result.result).toEqual({ ok: true });
    expect(result.files?.pdf).toBe(`${API_BASE}/download/user-1/resume.pdf`);
    expect(result.files?.source).toBe(`${API_BASE}/download/user-1/resume.docx`);
  });

  it('rejects when the stream reports a stage: error frame', async () => {
    mockStreamFetch([
      `data: ${JSON.stringify({ stage: 'error', message: 'generation blew up' })}\n\n`,
    ]);

    await expect(
      generateResumeStream('user-1', { job_description: 'jd', format: 'word' }, vi.fn())
    ).rejects.toThrow('generation blew up');
  });
});
