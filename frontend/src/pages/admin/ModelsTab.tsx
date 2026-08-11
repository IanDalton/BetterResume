import { useCallback, useEffect, useRef, useState } from 'react';
import { User } from 'firebase/auth';
import {
  fetchModelConfig,
  updateModelConfig,
  checkModels,
  type ModelConfigResponse,
  type ModelTask,
  type TaskModelConfig,
} from '../../services/api';
import { ModelPicker } from '../../components/admin/ModelPicker';
import { useToast } from '../../components/ui';

const TASK_META: Array<{ id: ModelTask; label: string; blurb: string }> = [
  { id: 'generation', label: 'Generation', blurb: 'Writes the resume. Needs tool calling.' },
  { id: 'translation', label: 'Translation', blurb: 'Translates non-English resumes.' },
  { id: 'import', label: 'Import', blurb: 'Extracts data from uploaded resume PDFs.' },
  { id: 'judge', label: 'Judge', blurb: 'Scores resumes in evaluation runs. Pick a model you are not evaluating.' },
];

function ModelSlot({ label, value, onChange, onClear, onTest, disabled }: {
  label: string; value: string | null; onChange: () => void; onClear?: () => void;
  onTest?: () => void; disabled?: boolean;
}) {
  return (
    <div className="mt-3">
      <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="font-mono text-xs break-all mt-1">{value ?? 'None'}</p>
      <div className="flex gap-2 mt-1">
        <button
          onClick={onChange}
          disabled={disabled}
          className="text-xs text-primary-500 hover:underline disabled:opacity-50 disabled:pointer-events-none disabled:no-underline"
        >
          Change
        </button>
        {onTest && value && (
          <button
            onClick={onTest}
            disabled={disabled}
            className="text-xs text-neutral-500 hover:underline disabled:opacity-50 disabled:pointer-events-none disabled:no-underline"
          >
            Test
          </button>
        )}
        {onClear && value && (
          <button
            onClick={onClear}
            disabled={disabled}
            className="text-xs text-neutral-500 hover:underline disabled:opacity-50 disabled:pointer-events-none disabled:no-underline"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
}

function formatUpdated(t: TaskModelConfig): string {
  return t.updated_at
    ? `Updated ${t.updated_at} by ${t.updated_by ?? 'unknown'}`
    : 'Never changed (using environment default)';
}

type PickerTarget = { task: ModelTask; slot: 'primary' | 'fallback' } | null;
type RejectedSave = { task: ModelTask; slot: 'primary' | 'fallback'; model: string | null; reason: string } | null;

export function ModelsTab({ user }: { user: User }) {
  const [config, setConfig] = useState<ModelConfigResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picker, setPicker] = useState<PickerTarget>(null);
  // A save the backend refused because the model failed its live check, kept so
  // the admin can store it anyway without re-picking it.
  const [rejected, setRejected] = useState<RejectedSave>(null);
  // The model currently being probed by the Test action, if any.
  const [testing, setTesting] = useState<string | null>(null);
  // Tasks with a save currently in flight -- disables that task's Change/Clear
  // controls so two overlapping saves for the same task (e.g. clicking Clear
  // on fallback right after picking a new primary) can never both be started
  // from the UI, which is what would let the second response's stale
  // "unmodified slot" value silently revert the first response's change.
  const [pendingTasks, setPendingTasks] = useState<Set<ModelTask>>(new Set());
  const { toast } = useToast();

  // Mirrors `config` so `applyModel` can read the freshest known config
  // synchronously without depending on the closure it was created in --
  // belt-and-suspenders alongside the `pendingTasks` guard above.
  const configRef = useRef<ModelConfigResponse | null>(null);
  useEffect(() => { configRef.current = config; }, [config]);

  // Stable across re-renders (identity only changes if `user` itself
  // changes), fetched fresh on every call -- passed straight to ModelPicker.
  const getToken = useCallback(() => user.getIdToken(), [user]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getToken()
      .then(token => fetchModelConfig(token))
      .then(c => { if (!cancelled) setConfig(c); })
      .catch(e => {
        if (cancelled) return;
        setError(e.message === 'forbidden' ? 'Access denied: this account is not authorized.' : `Failed to load model config: ${e.message}`);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [getToken]);

  /** Probe a model without saving anything -- for checking a slot that is
   *  already stored, or one saved before the check existed. */
  const testModel = async (model: string) => {
    setTesting(model);
    try {
      const [result] = await checkModels(await getToken(), [model]);
      toast({
        title: result.ok ? `${model} works` : `${model} cannot run`,
        description: result.message,
      });
    } catch (e: any) {
      setError(e.message === 'forbidden' ? 'Access denied: this account is not authorized.' : e.message);
    } finally {
      setTesting(null);
    }
  };

  const applyModel = async (
    task: ModelTask, slot: 'primary' | 'fallback', model: string | null, skipCheck = false,
  ) => {
    // Config-not-loaded and already-in-flight are both made unreachable from
    // the UI (controls are disabled/absent until config loads and while a
    // save for this task is pending) -- this is a defensive second guard,
    // not the primary mechanism.
    const latest = configRef.current;
    if (!latest || pendingTasks.has(task)) return;
    const current = latest.tasks[task];
    const primary = slot === 'primary' ? model! : current.primary;
    const fallback = slot === 'fallback' ? model : current.fallback;

    setPendingTasks(prev => new Set(prev).add(task));
    try {
      const updated = await updateModelConfig(await getToken(), task, primary, fallback, skipCheck);
      setConfig(updated);
      setError(null);
      setRejected(null);
      toast({ title: `${task} model updated`, description: updated.notice ?? undefined });
    } catch (e: any) {
      if (e.message === 'forbidden') {
        setError('Access denied: this account is not authorized.');
      } else {
        setError(e.message);
        // The save was refused by the live check, not by a transport failure --
        // offer to store it anyway rather than making the admin guess.
        if (/failed a live check/.test(e.message ?? '')) {
          setRejected({ task, slot, model, reason: e.message });
        }
      }
    } finally {
      setPendingTasks(prev => {
        const next = new Set(prev);
        next.delete(task);
        return next;
      });
    }
  };

  return (
    <>
      {loading && <p className="text-sm text-neutral-500">Loading…</p>}
      {error && <p className="text-sm text-red-500 dark:text-red-400">{error}</p>}
      {rejected && (
        <div className="mt-2 flex gap-3 text-xs">
          <button
            className="text-primary-500 hover:underline"
            onClick={() => {
              const r = rejected;
              setRejected(null);
              applyModel(r.task, r.slot, r.model, true);
            }}
          >
            Save {rejected.model ?? 'it'} anyway
          </button>
          <button className="text-neutral-500 hover:underline" onClick={() => { setRejected(null); setError(null); }}>
            Dismiss
          </button>
        </div>
      )}

      {config && (
        <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
          {TASK_META.map(meta => {
            const t = config.tasks[meta.id];
            const pending = pendingTasks.has(meta.id);
            return (
              <div key={meta.id} className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium">{meta.label}</h3>
                  {pending && <span className="text-[11px] text-neutral-400">Saving…</span>}
                </div>
                <p className="text-xs text-neutral-500 mt-0.5">{meta.blurb}</p>

                <ModelSlot
                  label="Primary"
                  value={t.primary}
                  onChange={() => setPicker({ task: meta.id, slot: 'primary' })}
                  onTest={() => testModel(t.primary)}
                  disabled={pending || testing !== null}
                />
                {t.supports_fallback && (
                  <ModelSlot
                    label="Fallback"
                    value={t.fallback}
                    onChange={() => setPicker({ task: meta.id, slot: 'fallback' })}
                    onClear={() => applyModel(meta.id, 'fallback', null)}
                    onTest={t.fallback ? () => testModel(t.fallback!) : undefined}
                    disabled={pending || testing !== null}
                  />
                )}

                <p className="text-[11px] text-neutral-500 mt-3 pt-3 border-t border-neutral-100 dark:border-neutral-800">
                  {formatUpdated(t)}
                </p>
              </div>
            );
          })}
        </div>
      )}

      <ModelPicker
        open={picker !== null}
        getToken={getToken}
        initialValue={picker ? config?.tasks[picker.task][picker.slot] ?? null : null}
        onSelect={(model) => {
          if (picker) applyModel(picker.task, picker.slot, model);
          setPicker(null);
        }}
        onClose={() => setPicker(null)}
      />
    </>
  );
}
