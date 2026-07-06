import React from 'react';
import { ResumeEntry } from '../../types';
import { Button } from '../ui';
import { useI18n } from '../../i18n';

interface EntryListProps {
  entries: ResumeEntry[];
  onEdit: (index: number) => void;
  onRemove: (index: number) => void;
  emptyLabel: string;
}

export const EntryList: React.FC<EntryListProps> = ({ entries, onEdit, onRemove, emptyLabel }) => {
  const { t } = useI18n();
  if (!entries.length) return <p className="text-sm text-neutral-500 dark:text-neutral-400">{emptyLabel}</p>;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {entries.map((e, i) => (
        <div
          key={i}
          className="rounded-lg border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-800/50"
        >
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
              {e.role}
              {e.company ? ` @ ${e.company}` : ''}
            </p>
            <div className="flex shrink-0 gap-2">
              <Button variant="link" size="xs" onClick={() => onEdit(i)}>{t('entry.edit')}</Button>
              <Button variant="danger" size="xs" onClick={() => onRemove(i)}>{t('entry.delete')}</Button>
            </div>
          </div>
          {e.location && <p className="text-xs text-neutral-600 dark:text-neutral-400">{e.location}</p>}
          {(e.start || e.end) && (
            <p className="text-xs text-neutral-500">
              {e.start || '—'} → {!e.end || e.end.toLowerCase() === 'present' ? t('present') : e.end}
            </p>
          )}
          {e.description && (
            <p className="mt-1 whitespace-pre-wrap text-xs text-neutral-700 dark:text-neutral-300">{e.description}</p>
          )}
        </div>
      ))}
    </div>
  );
};
