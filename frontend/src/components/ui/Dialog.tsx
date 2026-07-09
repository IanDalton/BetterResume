import React from 'react';
import * as RadixDialog from '@radix-ui/react-dialog';
import { cn } from './cn';

export type DialogSize = 'sm' | 'md' | 'lg';

const sizeClass: Record<DialogSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
};

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  size?: DialogSize;
  hideClose?: boolean;
}

export const Dialog: React.FC<DialogProps> = ({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = 'md',
  hideClose,
}) => (
  <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
    <RadixDialog.Portal>
      <RadixDialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
      <RadixDialog.Content
        className={cn(
          'fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-6 shadow-xl dark:bg-neutral-900 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95',
          sizeClass[size]
        )}
      >
        {title && (
          <RadixDialog.Title className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            {title}
          </RadixDialog.Title>
        )}
        {description && (
          <RadixDialog.Description className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
            {description}
          </RadixDialog.Description>
        )}
        <div className={cn(title || description ? 'mt-4' : undefined)}>{children}</div>
        {footer && <div className="mt-6 flex justify-end gap-3">{footer}</div>}
        {!hideClose && (
          <RadixDialog.Close
            className="absolute right-4 top-4 rounded text-neutral-500 hover:text-neutral-800 focus-ring dark:text-neutral-400 dark:hover:text-neutral-100"
            aria-label="Close"
          >
            ✕
          </RadixDialog.Close>
        )}
      </RadixDialog.Content>
    </RadixDialog.Portal>
  </RadixDialog.Root>
);
