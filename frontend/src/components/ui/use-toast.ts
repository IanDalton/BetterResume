import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';

export type ToastVariant = 'default' | 'success' | 'error';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  title: string;
  description?: string;
  variant?: ToastVariant;
  durationMs?: number;
  /** Optional call-to-action rendered inside the toast (e.g. "Retry", "Donate"). */
  action?: ToastAction;
  /** Called once when the toast leaves the screen for any reason (timeout, close, action). */
  onDismiss?: () => void;
}

export interface ToastItem extends ToastOptions {
  id: string;
}

interface ToastContextValue {
  toasts: ToastItem[];
  toast: (options: ToastOptions) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

let idCounter = 0;

export function useToastState(): ToastContextValue {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  // Mirror of `toasts` so `dismiss` can run the onDismiss side effect exactly once,
  // outside the state updater (updaters may be invoked twice in StrictMode).
  const toastsRef = useRef<ToastItem[]>([]);
  toastsRef.current = toasts;

  const dismiss = useCallback((id: string) => {
    const item = toastsRef.current.find((t) => t.id === id);
    if (!item) return;
    toastsRef.current = toastsRef.current.filter((t) => t.id !== id);
    setToasts((prev) => prev.filter((t) => t.id !== id));
    item.onDismiss?.();
  }, []);

  const toast = useCallback((options: ToastOptions) => {
    const id = `toast-${++idCounter}`;
    setToasts((prev) => [...prev, { id, ...options }]);
    return id;
  }, []);

  return useMemo(() => ({ toasts, toast, dismiss }), [toasts, toast, dismiss]);
}

export function useToast(): Pick<ToastContextValue, 'toast' | 'dismiss'> {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
}

export { ToastContext };
