import React from 'react';
import { cn } from './cn';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, invalid, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        'bg-white dark:bg-neutral-800 border rounded px-2 py-2 text-sm focus:outline-none focus:ring focus:ring-red-500',
        invalid
          ? 'border-red-500 dark:border-red-500'
          : 'border-neutral-300 dark:border-neutral-700',
        className
      )}
      aria-invalid={invalid || undefined}
      {...props}
    />
  )
);
Input.displayName = 'Input';
