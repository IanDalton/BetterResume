import { useEffect, useRef, useState } from 'react';
import { Dialog, Input, Button, Spinner } from '../ui';
import { fetchOpenRouterModels, type CatalogModel } from '../../services/api';

function formatContext(n: number | null): string {
  if (n == null) return '—';
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return String(n);
}

function formatPrice(p: number | null): string {
  return p == null ? '—' : `$${p.toFixed(2)}`;
}

export interface ModelPickerProps {
  open: boolean;
  /** Called fresh for every catalog request the picker makes (initial load,
   * each debounced search, each tools-only toggle) -- never resolved once and
   * cached, so a long-lived picker session can't reuse a stale token. */
  getToken: () => Promise<string>;
  initialValue: string | null;
  onSelect: (modelString: string) => void;
  onClose: () => void;
}

/** Modal for choosing a model string: searches the OpenRouter catalog (debounced,
 * tool-capable-only by default) or accepts a free-typed model string. The
 * free-text path must keep working even when the catalog fetch 503s -- an
 * admin locked out of the catalog must still be able to change models. */
export function ModelPicker({ open, getToken, initialValue, onSelect, onClose }: ModelPickerProps) {
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [toolsOnly, setToolsOnly] = useState(true);
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [freeText, setFreeText] = useState('');

  // Read via a ref rather than depending on `getToken` directly in the fetch
  // effect below, so the picker's request cadence never depends on whether
  // the caller happened to memoize the getter -- it just always calls
  // whatever the latest one is, fresh, per request.
  const getTokenRef = useRef(getToken);
  useEffect(() => { getTokenRef.current = getToken; }, [getToken]);

  // Reset transient state each time the picker opens.
  useEffect(() => {
    if (open) {
      setQuery('');
      setDebouncedQuery('');
      setToolsOnly(true);
      setError(null);
      setFreeText(initialValue ?? '');
    }
  }, [open, initialValue]);

  // Debounce the search box 250ms before it hits the catalog request.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 250);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getTokenRef.current()
      .then(token => fetchOpenRouterModels(token, { toolsOnly, q: debouncedQuery || undefined }))
      .then(list => { if (!cancelled) setModels(list); })
      .catch(e => {
        if (cancelled) return;
        setModels([]);
        setError(e.message === 'forbidden' ? 'Access denied.' : e.message);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [open, toolsOnly, debouncedQuery]);

  const handleFreeText = () => {
    const trimmed = freeText.trim();
    if (trimmed) onSelect(trimmed);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} title="Choose a model" size="lg">
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <Input
            placeholder="Search models…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="flex-1"
          />
          <label className="flex items-center gap-1.5 text-xs text-neutral-600 dark:text-neutral-400 whitespace-nowrap">
            <input
              type="checkbox"
              className="accent-primary-500"
              checked={toolsOnly}
              onChange={(e) => setToolsOnly(e.target.checked)}
            />
            Tool-capable only
          </label>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-8">
            <Spinner />
          </div>
        )}

        {!loading && error && (
          <div className="text-sm space-y-1">
            <p className="text-red-500 dark:text-red-400">{error}</p>
            <p className="text-neutral-500">Free-text entry still works.</p>
          </div>
        )}

        {!loading && !error && (
          <div className="max-h-80 overflow-y-auto border border-neutral-200 dark:border-neutral-700 rounded-lg divide-y divide-neutral-100 dark:divide-neutral-800">
            {models.length === 0 && (
              <p className="text-sm text-neutral-500 p-4">No models found.</p>
            )}
            {models.map(m => (
              <button
                key={m.id}
                type="button"
                onClick={() => onSelect(m.model_string)}
                className="w-full text-left p-3 hover:bg-neutral-50 dark:hover:bg-neutral-800 focus:outline-none focus:bg-neutral-50 dark:focus:bg-neutral-800"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs break-all">{m.id}</span>
                  {!m.supports_tools && (
                    <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
                      no tool support
                    </span>
                  )}
                </div>
                <p className="text-sm mt-0.5">{m.name}</p>
                <p className="text-xs text-neutral-500 mt-0.5">
                  {formatContext(m.context_length)} context · {formatPrice(m.prompt_price)} / {formatPrice(m.completion_price)} per Mtok
                </p>
                {!m.supports_tools && (
                  <p className="text-[11px] text-amber-700 dark:text-amber-400 mt-1">
                    Resume generation needs tool calling — this model will fail unless it is only used for import.
                  </p>
                )}
              </button>
            ))}
          </div>
        )}

        <div className="pt-2 border-t border-neutral-200 dark:border-neutral-700">
          <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">Or enter a model string manually</p>
          <div className="flex gap-2">
            <Input
              placeholder="e.g. openrouter:openai/gpt-4o"
              value={freeText}
              onChange={(e) => setFreeText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleFreeText(); }}
              className="flex-1 font-mono text-xs"
            />
            <Button variant="secondary" onClick={handleFreeText} disabled={!freeText.trim()}>Use this</Button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
