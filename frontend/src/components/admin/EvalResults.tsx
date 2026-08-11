import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchEvalComparison,
  fetchEvalRun,
  fetchEvalRuns,
  fetchModelConfig,
  downloadEvalResume,
  updateModelConfig,
  type EvalResult,
  type EvalRun,
  type ModelComparisonRow,
} from '../../services/api';
import { Button, Dialog, Spinner, useToast } from '../ui';

function formatDuration(ms: number | null): string {
  if (ms == null) return '—';
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatWhen(iso: string | null): string {
  if (!iso) return '—';
  return iso.replace('T', ' ').slice(0, 16);
}

/** Turns a bullet-point-style experience description into individual lines
 * for `<li>` rendering. The generation prompt asks for "3-4 bullets" but the
 * model is free to separate them with newlines or leading `-`/`•` markers;
 * this tolerates either (or neither, falling back to the whole string as one
 * line) rather than assuming a specific delimiter. */
function splitBullets(description: string | null | undefined): string[] {
  if (!description) return [];
  const lines = description
    .split(/\r?\n+/)
    .map(line => line.trim().replace(/^[-•*]\s*/, ''))
    .filter(Boolean);
  return lines.length > 0 ? lines : [description.trim()];
}

/** Renders `resume_json` (a `ResumeOutputFormat`, see backend/models/resume.py
 * and resume_section.py) as a readable resume rather than a raw JSON dump. */
function ResumePreview({ resumeJson }: { resumeJson: any }) {
  const section = resumeJson?.resume_section;
  if (!section) {
    return <p className="text-sm text-neutral-500">No resume content.</p>;
  }
  const experience: any[] = Array.isArray(section.experience) ? section.experience : [];
  const skills: any[] = Array.isArray(section.skills) ? section.skills : [];
  const education: any[] = Array.isArray(section.education) ? section.education : [];
  const languages: any[] = Array.isArray(section.languages) ? section.languages : [];

  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">{section.title}</h4>
        {resumeJson.language && <p className="text-[11px] text-neutral-500 mt-0.5">Language: {resumeJson.language}</p>}
      </div>

      {section.professional_summary && (
        <p className="text-sm text-neutral-700 dark:text-neutral-300">{section.professional_summary}</p>
      )}

      {experience.length > 0 && (
        <div>
          <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1.5">Experience</p>
          <div className="space-y-3">
            {experience.map((exp, i) => (
              <div key={i}>
                <p className="text-sm font-medium">
                  {exp.position}
                  {exp.company && <span className="font-normal text-neutral-500"> · {exp.company}</span>}
                </p>
                <p className="text-xs text-neutral-500">
                  {[exp.location, [exp.start_date, exp.end_date].filter(Boolean).join(' – ')]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                <ul className="list-disc list-inside text-sm mt-1 space-y-0.5 text-neutral-700 dark:text-neutral-300">
                  {splitBullets(exp.description).map((b, j) => (
                    <li key={j}>{b}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {skills.length > 0 && (
        <div>
          <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1.5">Skills</p>
          <ul className="text-sm space-y-0.5 text-neutral-700 dark:text-neutral-300">
            {skills.map((s, i) => (
              <li key={i}>
                <span className="font-medium text-neutral-900 dark:text-neutral-100">{s.name}</span>
                {s.description && <> — {s.description}</>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {education.length > 0 && (
        <div>
          <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1.5">Education</p>
          <ul className="text-sm space-y-0.5 text-neutral-700 dark:text-neutral-300">
            {education.map((e, i) => (
              <li key={i}>{[e.institution, e.degree, e.dates].filter(Boolean).join(' · ')}</li>
            ))}
          </ul>
        </div>
      )}

      {languages.length > 0 && (
        <div>
          <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1.5">Languages</p>
          <p className="text-sm text-neutral-700 dark:text-neutral-300">
            {languages.map((l: any) => `${l.name} (${l.proficiency})`).join(', ')}
          </p>
        </div>
      )}
    </div>
  );
}

type SortKey = 'schema' | 'ats' | 'judge' | 'composite' | 'latency' | 'tokens';

const SORT_GETTERS: Record<SortKey, (r: EvalResult) => number | null> = {
  schema: r => r.schema_score,
  ats: r => r.ats_score,
  judge: r => r.judge_overall,
  composite: r => r.composite_score,
  latency: r => r.duration_ms,
  tokens: r => (r.input_tokens == null && r.output_tokens == null ? null : (r.input_tokens ?? 0) + (r.output_tokens ?? 0)),
};

const SORT_HEADERS: Array<{ key: SortKey; label: string }> = [
  { key: 'schema', label: 'Schema' },
  { key: 'ats', label: 'ATS' },
  { key: 'judge', label: 'Judge' },
  { key: 'composite', label: 'Composite' },
  { key: 'latency', label: 'Latency' },
  { key: 'tokens', label: 'Tokens' },
];

/** Nulls always sort last, regardless of direction -- a missing score (e.g. a
 * failed cell) shouldn't jump to the top just because the direction flipped. */
function compareNullable(a: number | null, b: number | null, dir: 1 | -1): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return (a - b) * dir;
}

function fmtScore(v: number | null): string {
  return v == null ? '—' : v.toFixed(2);
}

function slug(s: string): string {
  return s.replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '').toLowerCase() || 'result';
}

export interface ResultsTableProps {
  results: EvalResult[];
  /** Fetched fresh per request (download, promote) -- never a resolved token
   * cached in state, matching the getToken discipline used by ModelPicker /
   * ModelsTab / EvalsTab. */
  getToken: () => Promise<string>;
  /** Called after a successful promote, purely as a notification hook -- the
   * confirm dialog, the `updateModelConfig` call, and the success/error toast
   * all live inside this component so every place that renders a
   * `ResultsTable` (the just-finished run, a history entry) gets promote
   * "for free". */
  onPromote?: (model: string) => void;
}

/** Routing concessions a model needed for a run (see backend/llm/model_routing.py).
 * Worth showing next to a score: a model graded with reasoning forced on costs
 * more per token, and one that only asks for its tool is less reliable than the
 * number alone suggests. */
function ConcessionBadges({ unforced, reasoning }: { unforced: boolean; reasoning: boolean }) {
  const tone = 'ml-1.5 inline-block text-[10px] px-1.5 py-0.5 rounded-full bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300';
  return (
    <>
      {unforced && <span className={tone} title="Rejects a forced tool choice; the tool is requested, not required">asks tool</span>}
      {reasoning && <span className={tone} title="Its endpoints will not accept reasoning disabled, so it runs with reasoning on">reasoning on</span>}
    </>
  );
}

export function ResultsTable({ results, getToken, onPromote }: ResultsTableProps) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'composite', dir: -1 });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState<Set<string>>(new Set());
  const [promoteTarget, setPromoteTarget] = useState<string | null>(null);
  const [promoting, setPromoting] = useState(false);
  const { toast } = useToast();

  const sorted = useMemo(() => {
    const getter = SORT_GETTERS[sort.key];
    return [...results].sort((a, b) => compareNullable(getter(a), getter(b), sort.dir));
  }, [results, sort]);

  const toggleSort = (key: SortKey) => {
    setSort(prev => (prev.key === key ? { key, dir: prev.dir === 1 ? -1 : 1 } : { key, dir: -1 }));
  };

  const toggleExpand = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleDownload = async (result: EvalResult, format: 'word' | 'latex') => {
    const key = `${result.id}:${format}`;
    setDownloading(prev => new Set(prev).add(key));
    try {
      const token = await getToken();
      const blob = await downloadEvalResume(token, result.id, format);
      const ext = format === 'latex' ? 'tex' : 'docx';
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `eval-${slug(result.model)}-${slug(result.jd_id ?? 'custom')}.${ext}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 5000);
    } catch (e: any) {
      toast({ title: 'Download failed', description: e.message === 'forbidden' ? 'Access denied.' : e.message, variant: 'error' });
    } finally {
      setDownloading(prev => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const confirmPromote = async () => {
    if (!promoteTarget) return;
    setPromoting(true);
    try {
      const token = await getToken();
      // Read the task's *current* fallback right before writing so the
      // promote can never blank it out -- only `primary` is meant to change.
      const config = await fetchModelConfig(token);
      const fallback = config.tasks.generation.fallback;
      await updateModelConfig(token, 'generation', promoteTarget, fallback);
      toast({ title: `${promoteTarget} is now the active generation model`, variant: 'success' });
      onPromote?.(promoteTarget);
      setPromoteTarget(null);
    } catch (e: any) {
      toast({ title: 'Promote failed', description: e.message === 'forbidden' ? 'Access denied.' : e.message, variant: 'error' });
    } finally {
      setPromoting(false);
    }
  };

  if (results.length === 0) {
    return <p className="text-sm text-neutral-500">No results.</p>;
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Model</th>
              <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">JD</th>
              <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Status</th>
              {SORT_HEADERS.map(h => (
                <th
                  key={h.key}
                  onClick={() => toggleSort(h.key)}
                  className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium cursor-pointer select-none hover:text-primary-500"
                >
                  {h.label}
                  {sort.key === h.key && <span className="ml-1 text-primary-500">{sort.dir === -1 ? '▼' : '▲'}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => {
              const isOpen = expanded.has(r.id);
              const hasResume = r.status !== 'error' && !!r.resume_json;
              return (
                <Fragment key={r.id}>
                  <tr
                    onClick={() => toggleExpand(r.id)}
                    className="cursor-pointer border-b border-neutral-100 dark:border-neutral-800 hover:bg-neutral-50 dark:hover:bg-neutral-800/60"
                  >
                    <td className="p-2 font-mono text-xs">
                      {r.model}
                      {r.fallback_used && (
                        <span className="ml-1.5 inline-block text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                          fallback
                        </span>
                      )}
                      <ConcessionBadges unforced={r.unforced_tool_choice} reasoning={r.allow_reasoning} />
                    </td>
                    <td className="p-2 text-xs text-neutral-600 dark:text-neutral-400">
                      {r.jd_id === 'custom' ? 'Custom JD' : r.jd_id ?? '—'}
                    </td>
                    <td className="p-2">
                      <span className={r.status === 'error' ? 'text-red-500 dark:text-red-400 font-medium text-xs' : 'text-green-600 dark:text-green-400 font-medium text-xs'}>
                        {r.status}
                      </span>
                    </td>
                    <td className="p-2 text-right font-mono">{fmtScore(r.schema_score)}</td>
                    <td className="p-2 text-right font-mono">{fmtScore(r.ats_score)}</td>
                    <td className="p-2 text-right font-mono">{fmtScore(r.judge_overall)}</td>
                    <td className="p-2 text-right font-mono font-semibold">{fmtScore(r.composite_score)}</td>
                    <td className="p-2 text-right text-neutral-500">{formatDuration(r.duration_ms)}</td>
                    <td className="p-2 text-right text-neutral-500 text-xs">
                      {r.input_tokens ?? '—'}/{r.output_tokens ?? '—'}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-neutral-100 dark:border-neutral-800">
                      <td colSpan={9} className="p-4 bg-neutral-50 dark:bg-neutral-900/60">
                        <div className="space-y-4">
                          {r.status === 'error' && (
                            <p className="text-sm text-red-500 dark:text-red-400">{r.error ?? 'This generation failed.'}</p>
                          )}

                          {r.judge_reasoning && (
                            <div>
                              <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">Judge reasoning</p>
                              <p className="text-sm whitespace-pre-wrap text-neutral-700 dark:text-neutral-300">{r.judge_reasoning}</p>
                            </div>
                          )}

                          {(r.missing_keywords?.length ?? 0) > 0 && (
                            <div>
                              <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">Missing keywords</p>
                              <div className="flex flex-wrap gap-1.5">
                                {r.missing_keywords?.map(k => (
                                  <span
                                    key={k}
                                    className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                                  >
                                    {k}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          {hasResume && <ResumePreview resumeJson={r.resume_json} />}

                          {hasResume && (
                            <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-neutral-200 dark:border-neutral-800">
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={(e) => { e.stopPropagation(); handleDownload(r, 'word'); }}
                                loading={downloading.has(`${r.id}:word`)}
                              >
                                Download Word
                              </Button>
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={(e) => { e.stopPropagation(); handleDownload(r, 'latex'); }}
                                loading={downloading.has(`${r.id}:latex`)}
                              >
                                Download LaTeX
                              </Button>
                              <Button
                                size="sm"
                                onClick={(e) => { e.stopPropagation(); setPromoteTarget(r.model); }}
                                className="ml-auto"
                              >
                                Promote to active
                              </Button>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog
        open={promoteTarget !== null}
        onOpenChange={(open) => { if (!open && !promoting) setPromoteTarget(null); }}
        title="Promote to active"
        description={promoteTarget ? `Use ${promoteTarget} for resume generation from now on?` : undefined}
        footer={
          <>
            <Button variant="secondary" onClick={() => setPromoteTarget(null)} disabled={promoting}>Cancel</Button>
            <Button onClick={confirmPromote} loading={promoting}>Confirm</Button>
          </>
        }
      />
    </>
  );
}

const STATUS_CLASS: Record<string, string> = {
  complete: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  running: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
  interrupted: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
};

function StatusChip({ status }: { status: string }) {
  const cls = STATUS_CLASS[status] ?? 'bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300';
  return <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>{status}</span>;
}

export interface RunHistoryProps {
  getToken: () => Promise<string>;
  /** Notified with the run id whenever a row is opened -- RunHistory fetches
   * and renders that run's ResultsTable itself, so this is informational
   * only (kept for callers that want to react, e.g. deep-linking). */
  onOpenRun?: (runId: string) => void;
}

export function RunHistory({ getToken, onOpenRun }: RunHistoryProps) {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [openRunId, setOpenRunId] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<EvalRun | null>(null);
  const [openResults, setOpenResults] = useState<EvalResult[] | null>(null);
  const [openLoading, setOpenLoading] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);
  // Bumped on every `openRow` call and compared after each await below, so a
  // slow response for a run the admin already clicked away from (e.g. click
  // run A, then click run B before A's fetch resolves) can never overwrite
  // what's currently on screen -- the same "cancelled" idea the mount-effect
  // fetches elsewhere in this file use, adapted for an imperative handler
  // that can be invoked repeatedly rather than a `useEffect` cleanup.
  const openRequestRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getToken()
      .then(token => fetchEvalRuns(token))
      .then(data => { if (!cancelled) setRuns(data); })
      .catch(e => {
        if (cancelled) return;
        setError(e.message === 'forbidden' ? 'Access denied.' : `Failed to load run history: ${e.message}`);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [getToken]);

  const openRow = async (run: EvalRun) => {
    if (openRunId === run.id) {
      setOpenRunId(null);
      return;
    }
    const requestId = ++openRequestRef.current;
    setOpenRunId(run.id);
    onOpenRun?.(run.id);
    setOpenLoading(true);
    setOpenError(null);
    setOpenRun(null);
    setOpenResults(null);
    try {
      const token = await getToken();
      const { run: fetchedRun, results } = await fetchEvalRun(token, run.id);
      if (openRequestRef.current !== requestId) return; // superseded by a later click
      setOpenRun(fetchedRun);
      setOpenResults(results);
    } catch (e: any) {
      if (openRequestRef.current !== requestId) return;
      setOpenError(e.message === 'forbidden' ? 'Access denied.' : e.message);
    } finally {
      if (openRequestRef.current === requestId) setOpenLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Spinner />
      </div>
    );
  }

  if (error) return <p className="text-sm text-red-500 dark:text-red-400">{error}</p>;
  if (runs.length === 0) return <p className="text-sm text-neutral-500">No eval runs yet.</p>;

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">When</th>
              <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Who</th>
              <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Status</th>
              <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Models</th>
              <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Data source</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">JDs</th>
            </tr>
          </thead>
          <tbody>
            {runs.map(run => {
              const jdCount = run.custom_jd ? 1 : run.jd_ids.length;
              const modelsLabel = run.models.length > 2
                ? `${run.models.slice(0, 2).join(', ')} +${run.models.length - 2}`
                : run.models.join(', ');
              return (
                <tr
                  key={run.id}
                  onClick={() => openRow(run)}
                  className={`cursor-pointer border-b border-neutral-100 dark:border-neutral-800 hover:bg-neutral-50 dark:hover:bg-neutral-800/60 ${openRunId === run.id ? 'bg-neutral-50 dark:bg-neutral-800/60' : ''}`}
                >
                  <td className="p-2 text-neutral-500 whitespace-nowrap">{formatWhen(run.created_at)}</td>
                  <td className="p-2 font-mono text-xs truncate max-w-[140px]" title={run.created_by ?? undefined}>{run.created_by ?? '—'}</td>
                  <td className="p-2"><StatusChip status={run.status} /></td>
                  <td className="p-2 font-mono text-xs" title={run.models.join(', ')}>{modelsLabel}</td>
                  <td className="p-2 text-neutral-600 dark:text-neutral-400 text-xs">{run.data_source}</td>
                  <td className="p-2 text-right">{jdCount}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {openRunId && (
        <div className="border-t border-neutral-200 dark:border-neutral-800 pt-4">
          {openLoading && (
            <div className="flex items-center justify-center py-8">
              <Spinner />
            </div>
          )}
          {openError && <p className="text-sm text-red-500 dark:text-red-400">{openError}</p>}
          {!openLoading && !openError && openRun && openResults && (
            <>
              {openRun.status === 'complete' && openResults.length === 0 && (
                <p className="text-sm text-amber-700 dark:text-amber-400 mb-3">
                  This run finished but no results were saved -- likely a database outage while it was running.
                </p>
              )}
              <ResultsTable results={openResults} getToken={getToken} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

export interface ModelComparisonProps {
  getToken: () => Promise<string>;
}

export function ModelComparison({ getToken }: ModelComparisonProps) {
  const [rows, setRows] = useState<ModelComparisonRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getToken()
      .then(token => fetchEvalComparison(token))
      .then(data => { if (!cancelled) setRows(data); })
      .catch(e => {
        if (cancelled) return;
        setError(e.message === 'forbidden' ? 'Access denied.' : `Failed to load comparison: ${e.message}`);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [getToken]);

  const sorted = useMemo(
    () => [...rows].sort((a, b) => (b.avg_composite ?? -Infinity) - (a.avg_composite ?? -Infinity)),
    [rows]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Spinner />
      </div>
    );
  }
  if (error) return <p className="text-sm text-red-500 dark:text-red-400">{error}</p>;
  if (sorted.length === 0) return <p className="text-sm text-neutral-500">No eval results yet.</p>;

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="text-left p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Model</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Runs</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Cells</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Success</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Composite</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Schema</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">ATS</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Judge</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Latency</th>
              <th className="text-right p-2 border-b border-neutral-200 dark:border-neutral-700 font-medium">Last run</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(row => (
              <tr key={row.model} className="border-b border-neutral-100 dark:border-neutral-800">
                <td className="p-2 font-mono text-xs">
                  {row.model}
                  <ConcessionBadges unforced={row.unforced_tool_choice} reasoning={row.allow_reasoning} />
                </td>
                <td className="p-2 text-right">{row.runs}</td>
                <td className="p-2 text-right">{row.cells}</td>
                <td className="p-2 text-right font-mono">{row.success_rate == null ? '—' : `${(row.success_rate * 100).toFixed(0)}%`}</td>
                <td className="p-2 text-right font-mono font-semibold">{fmtScore(row.avg_composite)}</td>
                <td className="p-2 text-right font-mono">{fmtScore(row.avg_schema)}</td>
                <td className="p-2 text-right font-mono">{fmtScore(row.avg_ats)}</td>
                <td className="p-2 text-right font-mono">{fmtScore(row.avg_judge)}</td>
                <td className="p-2 text-right text-neutral-500">{formatDuration(row.avg_duration_ms)}</td>
                <td className="p-2 text-right text-neutral-500 whitespace-nowrap">{row.last_run_at ? row.last_run_at.slice(0, 10) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-neutral-500">Aggregated across every stored eval result, including older runs.</p>
    </div>
  );
}
