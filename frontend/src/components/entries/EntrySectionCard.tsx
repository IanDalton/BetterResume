import React, { useRef, useState } from 'react';
import type { ZodSchema } from 'zod';
import { EntryType, ResumeEntry } from '../../types';
import { Dialog, Button } from '../ui';
import { EntryList } from './EntryList';
import { SectionStatusBadge } from './SectionStatusBadge';
import { issuesToFieldErrors, scrollToFirstInvalid } from './validation';
import { useI18n } from '../../i18n';

export interface EntrySectionCardProps {
  title: string;
  hint?: string;
  addLabel: string;
  emptyLabel: string;
  types: EntryType[];
  defaultType: EntryType;
  entries: ResumeEntry[];
  onAdd: (e: ResumeEntry) => void;
  onUpdate: (i: number, e: ResumeEntry) => void;
  onRemove: (i: number) => void;
  schema: ZodSchema<any>;
  renderFields: (props: {
    value: ResumeEntry;
    setField: (k: keyof ResumeEntry, v: string) => void;
    errors: Record<string, string>;
  }) => React.ReactNode;
  /** Whether the section has content. */
  isComplete: boolean;
  /** Whether generation is blocked while the section is empty (shows the "missing" badge). */
  required?: boolean;
}

const emptyEntryFor = (type: EntryType): ResumeEntry => ({
  type, role: '', company: '', location: '', start: '', end: '', description: '',
});

export const EntrySectionCard: React.FC<EntrySectionCardProps> = ({
  title, hint, addLabel, emptyLabel, types, defaultType, entries, onAdd, onUpdate, onRemove,
  schema, renderFields, isComplete, required,
}) => {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draft, setDraft] = useState<ResumeEntry>(emptyEntryFor(defaultType));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const formRef = useRef<HTMLDivElement | null>(null);

  const indexed = entries.map((e, i) => ({ e, i })).filter(({ e }) => types.includes(e.type));

  const openAdd = () => {
    setDraft(emptyEntryFor(defaultType));
    setErrors({});
    setEditingIndex(null);
    setOpen(true);
  };
  const openEdit = (globalIndex: number) => {
    setDraft(entries[globalIndex]);
    setErrors({});
    setEditingIndex(globalIndex);
    setOpen(true);
  };
  const setField = (k: keyof ResumeEntry, v: string) => setDraft((d) => ({ ...d, [k]: v }));

  const submit = () => {
    const result = schema.safeParse(draft);
    if (!result.success) {
      setErrors(issuesToFieldErrors(result.error.issues));
      scrollToFirstInvalid(formRef.current);
      return;
    }
    if (editingIndex == null) onAdd(draft);
    else onUpdate(editingIndex, draft);
    setOpen(false);
  };

  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-base font-semibold text-neutral-900 dark:text-neutral-100">
            {title}
            <SectionStatusBadge complete={isComplete} required={required} />
          </h3>
          {hint && <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{hint}</p>}
        </div>
        <Button size="sm" variant="secondary" onClick={openAdd}>{addLabel}</Button>
      </div>
      <EntryList
        entries={indexed.map(({ e }) => e)}
        emptyLabel={emptyLabel}
        onEdit={(localIdx) => openEdit(indexed[localIdx].i)}
        onRemove={(localIdx) => onRemove(indexed[localIdx].i)}
      />
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={editingIndex == null ? addLabel : t('button.updateEntry')}
        size="lg"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>{t('button.cancel')}</Button>
            <Button variant="primary" onClick={submit}>
              {editingIndex == null ? t('button.addEntry') : t('button.updateEntry')}
            </Button>
          </>
        }
      >
        <div ref={formRef} className="grid gap-4 sm:grid-cols-2">
          {renderFields({ value: draft, setField, errors })}
        </div>
      </Dialog>
    </div>
  );
};
