import React from 'react';
import { cn } from './cn';

export interface TabItem<T extends string> {
  id: T;
  label: string;
}

export interface TabsProps<T extends string> {
  tabs: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  className?: string;
  'aria-label'?: string;
}

/** Underlined tab strip shared by the admin dashboard and its sub-views. */
export function Tabs<T extends string>({ tabs, value, onChange, className, ...aria }: TabsProps<T>) {
  return (
    <nav className={cn('flex gap-1 border-b border-neutral-200 dark:border-neutral-800', className)} role="tablist" {...aria}>
      {tabs.map((tab) => {
        const active = tab.id === value;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            className={cn(
              'px-3 py-2 min-h-[40px] text-sm border-b-2 -mb-px focus-ring rounded-t-lg',
              active
                ? 'border-red-500 text-red-600 dark:text-red-400'
                : 'border-transparent text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200'
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}
