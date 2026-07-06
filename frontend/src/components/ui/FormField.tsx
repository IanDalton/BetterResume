import React from 'react';
import * as Label from '@radix-ui/react-label';
import { cn } from './cn';

export interface FormFieldProps {
  label: string;
  htmlFor?: string;
  error?: string;
  hint?: string;
  required?: boolean;
  className?: string;
  children: React.ReactNode;
}

export const FormField: React.FC<FormFieldProps> = ({
  label,
  htmlFor,
  error,
  hint,
  required,
  className,
  children,
}) => (
  <div className={cn('flex flex-col gap-1', className)}>
    <Label.Root
      htmlFor={htmlFor}
      className="text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400"
    >
      {label}
      {required && <span className="ml-0.5 text-red-500">*</span>}
    </Label.Root>
    {children}
    {error ? (
      <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
    ) : hint ? (
      <p className="text-xs text-neutral-500 dark:text-neutral-500">{hint}</p>
    ) : null}
  </div>
);
