import React from 'react';
import * as RadixSelect from '@radix-ui/react-select';
import { cn } from './cn';

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  options: SelectOption[];
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  invalid?: boolean;
  className?: string;
  disabled?: boolean;
  'aria-label'?: string;
}

export const Select: React.FC<SelectProps> = ({
  options,
  value,
  onValueChange,
  placeholder,
  invalid,
  className,
  disabled,
  ...aria
}) => (
  <RadixSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
    <RadixSelect.Trigger
      className={cn(
        'inline-flex items-center justify-between gap-2 bg-white dark:bg-neutral-800 border rounded px-2 py-2 text-sm focus:outline-none focus:ring focus:ring-red-500 disabled:opacity-50 disabled:cursor-not-allowed',
        invalid ? 'border-red-500 dark:border-red-500' : 'border-neutral-300 dark:border-neutral-700',
        className
      )}
      aria-invalid={invalid || undefined}
      {...aria}
    >
      <RadixSelect.Value placeholder={placeholder} />
      <RadixSelect.Icon>▾</RadixSelect.Icon>
    </RadixSelect.Trigger>
    <RadixSelect.Portal>
      <RadixSelect.Content
        className="z-50 overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-xl dark:border-neutral-700 dark:bg-neutral-800 animate-in fade-in-0 zoom-in-95"
        position="popper"
        sideOffset={4}
      >
        <RadixSelect.Viewport className="p-1">
          {options.map((opt) => (
            <RadixSelect.Item
              key={opt.value}
              value={opt.value}
              className="relative flex cursor-pointer select-none items-center rounded px-3 py-2 text-sm outline-none data-[highlighted]:bg-red-50 data-[highlighted]:text-red-900 dark:data-[highlighted]:bg-red-900/30 dark:data-[highlighted]:text-red-100"
            >
              <RadixSelect.ItemText>{opt.label}</RadixSelect.ItemText>
            </RadixSelect.Item>
          ))}
        </RadixSelect.Viewport>
      </RadixSelect.Content>
    </RadixSelect.Portal>
  </RadixSelect.Root>
);
