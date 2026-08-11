import { useCallback, useEffect, useMemo, useState } from 'react';
import { User } from 'firebase/auth';
import {
  fetchEvalFixtures,
  fetchEvalRun,
  startEvalRun,
  streamEvalRun,
  checkModels,
  type EvalResult,
  type ModelCheckResult,
} from '../../services/api';
import { ModelPicker } from '../../components/admin/ModelPicker';
import { ResultsTable, RunHistory, ModelComparison } from '../../components/admin';
import { Button, Card, CardContent, CardHeader, CardTitle, Spinner, Textarea, useToast } from '../../components/ui';

const MAX_MODELS = 5;
const MAX_CELLS = 20;

type DataSource = 'fixture' | 'mine';
type SubTab = 'new' | 'history' | 'compare';

const SUB_TABS: Array<{ id: SubTab; label: string }> = [
  { id: 'new', label: 'New run' },
  { id: 'history', label: 'History' },
  { id: 'compare', label: 'Compare' },
];

interface JdFixture {
  id: string;
  label: string;
  preview: string;
}

/** Keys a cell by (model, jd) so live SSE updates and the grid lookup agree
 * on identity. `jd_id` comes back typed nullable from the API even though in
 * practice every cell we render has one (a fixture id or `'custom'`). */
const cellKey = (model: string, jdId: string | null) => `${model}::${jdId ?? ''}`;

function formatDuration(ms: number | null): string {
  if (ms == null) return '—';
  return `${(ms / 1000).toFixed(1)}s`;
}

function EvalCell({ result }: { result: EvalResult | undefined }) {
  if (!result) {
    return (
      <div className="flex items-center justify-center py-4">
        <Spinner size="sm" />
      </div>
    );
  }

  if (result.status === 'error') {
    return (
      <div className="py-2 text-center" title={result.error ?? 'Unknown error'}>
        <span className="text-sm font-semibold text-red-500 dark:text-red-400">ERROR</span>
      </div>
    );
  }

  return (
    <div className="py-2 text-center space-y-0.5">
      <div className="text-lg font-semibold">
        {result.composite_score != null ? result.composite_score.toFixed(1) : '—'}
      </div>
      <div
        className={
          result.schema_passed
            ? 'text-xs font-medium text-green-600 dark:text-green-400'
            : 'text-xs font-medium text-red-500 dark:text-red-400'
        }
      >
        {result.schema_passed ? 'PASS' : 'FAIL'}
      </div>
      <div className="text-xs text-neutral-500">{formatDuration(result.duration_ms)}</div>
      {result.fallback_used && (
        <span className="inline-block mt-0.5 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
          fallback
        </span>
      )}
    </div>
  );
}

/** What the pre-flight learned about one model: ready, ready with a routing
 * concession (see backend/llm/model_routing.py), or unable to run at all. */
function CheckBadge({ check }: { check: ModelCheckResult | undefined }) {
  if (!check) return null;
  const concessions = [
    check.forced_tool_choice ? null : 'asks tool',
    check.reasoning_disabled ? null : 'reasoning on',
  ].filter(Boolean);
  const [text, tone] = !check.ok
    ? ['cannot run', 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300']
    : concessions.length
      ? [concessions.join(', '), 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300']
      : ['ready', 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300'];
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${tone}`} title={check.message}>
      {text}
    </span>
  );
}

export function EvalsTab({ user }: { user: User }) {
  const [subTab, setSubTab] = useState<SubTab>('new');
  const [fixtures, setFixtures] = useState<JdFixture[]>([]);
  const [judgeModel, setJudgeModel] = useState<string | null>(null);
  const [fixturesLoading, setFixturesLoading] = useState(false);
  const [fixturesError, setFixturesError] = useState<string | null>(null);

  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [selectedJds, setSelectedJds] = useState<string[]>([]);
  const [customJd, setCustomJd] = useState('');
  const [dataSource, setDataSource] = useState<DataSource>('fixture');
  const [pickerOpen, setPickerOpen] = useState(false);
  // Pre-flight results, keyed by model. A run costs real money per cell, so
  // every selected model is asked to serve one tiny request first; a model
  // that cannot is reported here instead of consuming its share of the run.
  const [checks, setChecks] = useState<Record<string, ModelCheckResult>>({});
  const [checking, setChecking] = useState(false);
  // Set when a pre-flight found a broken model, so the next click means
  // "run anyway" rather than silently repeating the same check.
  const [checkBlocked, setCheckBlocked] = useState(false);

  const [cells, setCells] = useState<Record<string, EvalResult>>({});
  const [runId, setRunId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  // The model/JD lists the *in-flight (or last-completed) run* was actually
  // submitted with. The grid renders against these rather than the live
  // `selectedModels`/`selectedJds` so that editing the form after a run
  // finishes (to set up the next one) can't reshuffle or orphan cells that
  // are still on screen from the previous run.
  const [runModels, setRunModels] = useState<string[]>([]);
  const [runJdIds, setRunJdIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const { toast } = useToast();

  // Stable across re-renders, fetched fresh on every call -- passed straight
  // to ModelPicker (never a resolved token cached in state).
  const getToken = useCallback(() => user.getIdToken(), [user]);

  useEffect(() => {
    let cancelled = false;
    setFixturesLoading(true);
    setFixturesError(null);
    getToken()
      .then(token => fetchEvalFixtures(token))
      .then(data => {
        if (cancelled) return;
        setFixtures(data.job_descriptions);
        setJudgeModel(data.default_judge_model);
      })
      .catch(e => {
        if (cancelled) return;
        setFixturesError(e.message === 'forbidden' ? 'Access denied.' : `Failed to load fixtures: ${e.message}`);
      })
      .finally(() => { if (!cancelled) setFixturesLoading(false); });
    return () => { cancelled = true; };
  }, [getToken]);

  const jdIdsForRun = customJd.trim() ? ['custom'] : selectedJds;
  const totalCells = selectedModels.length * jdIdsForRun.length;
  const runTotalCells = runModels.length * runJdIds.length;
  const doneCells = runModels.reduce(
    (n, m) => n + runJdIds.filter(jd => cells[cellKey(m, jd)]).length,
    0
  );

  const removeModel = (model: string) => {
    setSelectedModels(prev => prev.filter(m => m !== model));
  };

  const addModel = (model: string) => {
    setSelectedModels(prev => (prev.includes(model) ? prev : [...prev, model]));
    setPickerOpen(false);
  };

  /** Probe the selected models. Returns the ones that cannot serve a run. */
  const runPreflight = async (): Promise<ModelCheckResult[]> => {
    setChecking(true);
    try {
      const results = await checkModels(await user.getIdToken(), selectedModels);
      setChecks(Object.fromEntries(results.map(r => [r.model, r])));
      return results.filter(r => !r.ok);
    } finally {
      setChecking(false);
    }
  };

  const checkNow = async () => {
    setError(null);
    try {
      const broken = await runPreflight();
      setCheckBlocked(broken.length > 0);
      toast(broken.length
        ? { title: `${broken.length} model(s) cannot run`, description: broken.map(b => b.model).join(', ') }
        : { title: 'All selected models are ready' });
    } catch (e: any) {
      setError(e.message === 'forbidden' ? 'Access denied.' : e.message);
    }
  };

  const toggleJd = (id: string) => {
    setSelectedJds(prev => (prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]));
  };

  const start = async () => {
    setError(null);
    // Pre-flight unless the admin already saw the failures and clicked again.
    if (!checkBlocked) {
      try {
        const broken = await runPreflight();
        if (broken.length > 0) {
          setCheckBlocked(true);
          setError(
            `${broken.map(b => `${b.model} (${b.message})`).join('; ')}. ` +
            'Deselect these, or press Run evaluation again to run anyway.'
          );
          return;
        }
      } catch (e: any) {
        // A pre-flight that cannot run is not a reason to block the run the
        // admin actually asked for -- note it and carry on.
        setError(`Model pre-flight failed (${e.message}); running without it.`);
      }
    }
    setCheckBlocked(false);
    setRunning(true);
    setCells({});
    setRunModels(selectedModels);
    setRunJdIds(jdIdsForRun);
    try {
      const idToken = await user.getIdToken();
      const { run_id } = await startEvalRun(idToken, {
        models: selectedModels,
        jd_ids: customJd.trim() ? [] : selectedJds,
        custom_jd: customJd.trim() || null,
        data_source: dataSource === 'mine' ? `user:${user.uid}` : 'fixture',
        judge_model: judgeModel,
        notes: null,
      });
      setRunId(run_id);
      try {
        await streamEvalRun(idToken, run_id, cell => {
          setCells(prev => ({ ...prev, [cellKey(cell.model, cell.jd_id)]: cell }));
        });
        toast({ title: 'Eval run complete' });
      } catch (streamErr: any) {
        // The stream connection failing (including a 404 -- the backend pops
        // its in-flight queue the instant the run ends, with no grace
        // window, so a run that finishes fast can beat our GET here) does
        // NOT mean the run failed: every cell that ran was already
        // persisted. Recover from the persisted record rather than losing
        // an outcome the admin never gets to see. `forbidden` needs no
        // recovery attempt -- the follow-up fetch would fail the same way.
        if (streamErr?.message === 'forbidden') throw streamErr;
        const recovered = await fetchEvalRun(idToken, run_id).catch(() => null);
        if (!recovered) throw streamErr;
        const byKey: Record<string, EvalResult> = {};
        for (const r of recovered.results) byKey[cellKey(r.model, r.jd_id)] = r;
        setCells(prev => ({ ...prev, ...byKey }));
        if (recovered.run.status === 'complete') {
          // The run itself finished fine; only the live stream connection
          // was lost. Not a failure from the admin's point of view.
          toast({ title: 'Eval run complete', description: 'Live updates were interrupted, but every result was recovered.' });
        } else {
          // A genuine run failure (or interruption) -- say so, but the grid
          // above still shows whatever cells did complete and persist.
          setError(`Eval run ${recovered.run.status}. Showing the results that completed before it stopped.`);
        }
      }
    } catch (e: any) {
      setError(e.message === 'forbidden' ? 'Access denied.' : e.message);
    } finally {
      setRunId(null);
      setRunning(false);
    }
  };

  const runDisabled = running || totalCells === 0 || totalCells > MAX_CELLS;

  // Once a run finishes, the "New run" pane swaps its live grid for a
  // ResultsTable of the same cells (in run order) so the admin lands
  // straight on the detail view without navigating to History.
  const finishedResults = useMemo(() => {
    if (running || runModels.length === 0) return [];
    const out: EvalResult[] = [];
    for (const m of runModels) {
      for (const jd of runJdIds) {
        const cell = cells[cellKey(m, jd)];
        if (cell) out.push(cell);
      }
    }
    return out;
  }, [running, runModels, runJdIds, cells]);

  return (
    <div className="space-y-6">
      <nav className="flex gap-1 border-b border-neutral-200 dark:border-neutral-800">
        {SUB_TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setSubTab(t.id)}
            className={`px-3 py-2 text-sm border-b-2 -mb-px ${subTab === t.id
              ? 'border-primary-500 text-primary-500'
              : 'border-transparent text-neutral-500 hover:text-neutral-300'}`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {subTab === 'new' && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>New run</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div>
                <p className="text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400 mb-1.5">Models</p>
                <div className="flex flex-wrap items-center gap-2">
                  {selectedModels.map(m => (
                    <span
                      key={m}
                      className="inline-flex items-center gap-1.5 rounded-full bg-neutral-100 dark:bg-neutral-800 border border-neutral-200 dark:border-neutral-700 px-2.5 py-1 text-xs font-mono"
                    >
                      {m}
                      <CheckBadge check={checks[m]} />
                      <button
                        type="button"
                        onClick={() => removeModel(m)}
                        disabled={running}
                        aria-label={`Remove ${m}`}
                        className="text-neutral-400 hover:text-red-500 disabled:opacity-50 disabled:pointer-events-none"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => setPickerOpen(true)}
                    disabled={running || selectedModels.length >= MAX_MODELS}
                  >
                    Add model
                  </Button>
                </div>
                {selectedModels.length >= MAX_MODELS && (
                  <p className="text-xs text-neutral-500 mt-1">Maximum 5 models per run.</p>
                )}
                {selectedModels.length > 0 && (
                  <button
                    type="button"
                    onClick={checkNow}
                    disabled={running || checking}
                    className="text-xs text-primary-500 hover:underline mt-1 disabled:opacity-50 disabled:pointer-events-none"
                  >
                    {checking ? 'Checking…' : 'Check models'}
                  </button>
                )}
              </div>

              <div>
                <p className="text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400 mb-1.5">
                  Job descriptions
                </p>
                {fixturesLoading && <p className="text-sm text-neutral-500">Loading fixtures…</p>}
                {fixturesError && <p className="text-sm text-red-500 dark:text-red-400">{fixturesError}</p>}
                {!fixturesLoading && !fixturesError && (
                  <div className="space-y-1.5 mb-3">
                    {fixtures.map(f => (
                      <label key={f.id} className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-0.5 accent-primary-500"
                          checked={selectedJds.includes(f.id)}
                          onChange={() => toggleJd(f.id)}
                          disabled={running || customJd.trim() !== ''}
                        />
                        <span>
                          <span className="font-medium">{f.label}</span>
                          <span className="block text-xs text-neutral-500">{f.preview}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                )}
                <Textarea
                  placeholder="Paste a custom job description…"
                  value={customJd}
                  onChange={e => setCustomJd(e.target.value)}
                  disabled={running || selectedJds.length > 0}
                />
              </div>

              <div>
                <p className="text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400 mb-1.5">
                  Data source
                </p>
                <div className="flex gap-4 text-sm">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="eval-data-source"
                      className="accent-primary-500"
                      checked={dataSource === 'fixture'}
                      onChange={() => setDataSource('fixture')}
                      disabled={running}
                    />
                    Fixture profile (deterministic)
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="eval-data-source"
                      className="accent-primary-500"
                      checked={dataSource === 'mine'}
                      onChange={() => setDataSource('mine')}
                      disabled={running}
                    />
                    My stored profile
                  </label>
                </div>
              </div>

              <p className="text-xs text-neutral-500">
                {selectedModels.length} models × {jdIdsForRun.length} job descriptions = {totalCells} generations,
                each with one judge call.
              </p>
              <p className="text-xs text-neutral-500">
                Judge: <span className="font-mono">{judgeModel ?? 'none'}</span> — change it under the Models tab.
              </p>
              {totalCells > MAX_CELLS && (
                <p className="text-xs text-red-500 dark:text-red-400">Maximum 20 cells per run.</p>
              )}

              <Button onClick={start} loading={running || checking} disabled={runDisabled}>
                {checkBlocked ? 'Run anyway' : 'Run evaluation'}
              </Button>
              <p className="text-xs text-neutral-500">
                Each model is asked to serve one tiny request before the run starts, so a model that
                cannot do the job does not spend cells failing.
              </p>

              {error && <p className="text-sm text-red-500 dark:text-red-400">{error}</p>}
            </CardContent>
          </Card>

          {runModels.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>{running ? 'Live results' : 'Results'}</CardTitle>
              </CardHeader>
              <CardContent>
                {running ? (
                  <>
                    <p className="text-sm text-neutral-500 mb-3">
                      {doneCells} / {runTotalCells} cells complete
                      {runId && <span className="text-neutral-400"> · run {runId}</span>}
                    </p>
                    <div className="overflow-x-auto">
                      <table className="min-w-full border-collapse text-sm">
                        <thead>
                          <tr>
                            <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">
                              Model
                            </th>
                            {runJdIds.map(jd => (
                              <th
                                key={jd}
                                className="text-center p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium"
                              >
                                {jd === 'custom' ? 'Custom JD' : fixtures.find(f => f.id === jd)?.label ?? jd}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {runModels.map(m => (
                            <tr key={m}>
                              <th className="text-left p-2 border-b border-neutral-100 dark:border-neutral-800 font-mono text-xs font-normal align-top">
                                {m}
                              </th>
                              {runJdIds.map(jd => (
                                <td key={jd} className="p-2 border-b border-neutral-100 dark:border-neutral-800">
                                  <EvalCell result={cells[cellKey(m, jd)]} />
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <ResultsTable results={finishedResults} getToken={getToken} />
                )}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {subTab === 'history' && (
        <Card>
          <CardHeader>
            <CardTitle>Run history</CardTitle>
          </CardHeader>
          <CardContent>
            <RunHistory getToken={getToken} />
          </CardContent>
        </Card>
      )}

      {subTab === 'compare' && (
        <Card>
          <CardHeader>
            <CardTitle>Model comparison</CardTitle>
          </CardHeader>
          <CardContent>
            <ModelComparison getToken={getToken} />
          </CardContent>
        </Card>
      )}

      <ModelPicker
        open={pickerOpen}
        getToken={getToken}
        initialValue={null}
        onSelect={addModel}
        onClose={() => setPickerOpen(false)}
      />
    </div>
  );
}
