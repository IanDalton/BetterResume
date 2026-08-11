import { useEffect, useState } from 'react';
import { User } from 'firebase/auth';
import {
  fetchModelConfig,
  updateModelConfig,
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
];

function ModelSlot({ label, value, onChange, onClear }: {
  label: string; value: string | null; onChange: () => void; onClear?: () => void;
}) {
  return (
    <div className="mt-3">
      <p className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="font-mono text-xs break-all mt-1">{value ?? 'None'}</p>
      <div className="flex gap-2 mt-1">
        <button onClick={onChange} className="text-xs text-primary-500 hover:underline">Change</button>
        {onClear && value && (
          <button onClick={onClear} className="text-xs text-neutral-500 hover:underline">Clear</button>
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

type PickerTarget = { task: ModelTask; slot: 'primary' | 'fallback'; idToken: string } | null;

export function ModelsTab({ user }: { user: User }) {
  const [config, setConfig] = useState<ModelConfigResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picker, setPicker] = useState<PickerTarget>(null);
  const { toast } = useToast();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    user.getIdToken()
      .then(token => fetchModelConfig(token))
      .then(c => { if (!cancelled) setConfig(c); })
      .catch(e => {
        if (cancelled) return;
        setError(e.message === 'forbidden' ? 'Access denied: this account is not authorized.' : `Failed to load model config: ${e.message}`);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [user]);

  const applyModel = async (task: ModelTask, slot: 'primary' | 'fallback', model: string | null) => {
    const current = config!.tasks[task];
    const primary = slot === 'primary' ? model! : current.primary;
    const fallback = slot === 'fallback' ? model : current.fallback;
    try {
      setConfig(await updateModelConfig(await user.getIdToken(), task, primary, fallback));
      toast({ title: `${task} model updated` });
    } catch (e: any) {
      setError(e.message === 'forbidden' ? 'Access denied: this account is not authorized.' : e.message);
    }
  };

  const openPicker = async (task: ModelTask, slot: 'primary' | 'fallback') => {
    // Fresh token for the picker's lifetime -- it may issue several catalog
    // searches while open, but never reuses a token across separate opens.
    const idToken = await user.getIdToken();
    setPicker({ task, slot, idToken });
  };

  return (
    <>
      {loading && <p className="text-sm text-neutral-500">Loading…</p>}
      {error && <p className="text-sm text-red-500 dark:text-red-400">{error}</p>}

      {config && (
        <div className="grid md:grid-cols-3 gap-4">
          {TASK_META.map(meta => {
            const t = config.tasks[meta.id];
            return (
              <div key={meta.id} className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
                <h3 className="text-sm font-medium">{meta.label}</h3>
                <p className="text-xs text-neutral-500 mt-0.5">{meta.blurb}</p>

                <ModelSlot
                  label="Primary"
                  value={t.primary}
                  onChange={() => openPicker(meta.id, 'primary')}
                />
                <ModelSlot
                  label="Fallback"
                  value={t.fallback}
                  onChange={() => openPicker(meta.id, 'fallback')}
                  onClear={() => applyModel(meta.id, 'fallback', null)}
                />

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
        idToken={picker?.idToken ?? ''}
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
