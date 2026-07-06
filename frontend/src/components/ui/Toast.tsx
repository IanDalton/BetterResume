import React from 'react';
import * as RadixToast from '@radix-ui/react-toast';
import { cn } from './cn';
import { ToastContext, useToastState, type ToastVariant } from './use-toast';

const variantClass: Record<ToastVariant, string> = {
  default: 'border-neutral-200 bg-white dark:border-neutral-700 dark:bg-neutral-800',
  success: 'border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-900/40',
  error: 'border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-900/40',
};

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const state = useToastState();

  return (
    <ToastContext.Provider value={state}>
      <RadixToast.Provider swipeDirection="right">
        {children}
        {state.toasts.map((t) => (
          <RadixToast.Root
            key={t.id}
            duration={t.durationMs ?? 5000}
            className={cn(
              'relative rounded-lg border p-4 pr-8 shadow-lg data-[state=open]:animate-in data-[state=closed]:animate-out data-[swipe=end]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-bottom-2',
              variantClass[t.variant ?? 'default']
            )}
            onOpenChange={(open) => {
              if (!open) state.dismiss(t.id);
            }}
          >
            <RadixToast.Title className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
              {t.title}
            </RadixToast.Title>
            {t.description && (
              <RadixToast.Description className="mt-1 text-sm text-neutral-700 dark:text-neutral-300">
                {t.description}
              </RadixToast.Description>
            )}
            <RadixToast.Close
              className="absolute right-2 top-2 text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
              aria-label="Dismiss"
            >
              ✕
            </RadixToast.Close>
          </RadixToast.Root>
        ))}
        <RadixToast.Viewport className="fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2 outline-none" />
      </RadixToast.Provider>
    </ToastContext.Provider>
  );
};
