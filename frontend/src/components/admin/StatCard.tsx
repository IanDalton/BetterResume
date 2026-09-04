import React from 'react';

interface StatCardProps {
  label: string;
  value: React.ReactNode;
  hint?: string;
  /** DOM id of the table this number summarizes; makes the whole card a link to it. */
  targetId?: string;
}

export function StatCard({ label, value, hint, targetId }: StatCardProps) {
  const body = (
    <>
      <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="text-2xl font-semibold mt-1">{value}</p>
      {hint && <p className="text-xs text-neutral-500 mt-1">{hint}</p>}
      {targetId && <p className="text-xs text-red-600 dark:text-red-400 mt-2">See table ↓</p>}
    </>
  );
  const className = 'block bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm';
  if (!targetId) return <div className={className}>{body}</div>;
  return (
    <a
      href={`#${targetId}`}
      className={`${className} hover:border-red-400 dark:hover:border-red-500 focus-ring`}
      onClick={(e) => {
        const el = document.getElementById(targetId);
        if (el) {
          e.preventDefault();
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }}
    >
      {body}
    </a>
  );
}
