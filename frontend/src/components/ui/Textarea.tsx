import React from 'react';
import { cn } from './cn';

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, invalid, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        'bg-white dark:bg-neutral-800 border rounded px-2 py-2 text-sm min-h-[100px] resize-y focus:outline-none focus:ring focus:ring-red-500',
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
Textarea.displayName = 'Textarea';
