import React from 'react';
import { Dialog } from './Dialog';
import { Button } from './Button';

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  /** Use the danger button style for irreversible/destructive confirmations (default true). */
  destructive?: boolean;
}

/**
 * Shared confirmation dialog for destructive or otherwise consequential actions.
 * Reuses the app's Dialog/Button design system instead of the native window.confirm().
 */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel,
  onConfirm,
  destructive = true,
}) => (
  <Dialog
    open={open}
    onOpenChange={onOpenChange}
    size="sm"
    title={title}
    description={description}
    footer={
      <>
        <Button variant="secondary" onClick={() => onOpenChange(false)}>{cancelLabel}</Button>
        <Button
          variant={destructive ? 'danger' : 'primary'}
          onClick={() => {
            onConfirm();
            onOpenChange(false);
          }}
        >
          {confirmLabel}
        </Button>
      </>
    }
  />
);
