import React, { useState } from 'react';
import { LanguageEntry } from '../../types';
import { Dialog, Button, FormField, Input, Select } from '../ui';
import { languageEntrySchema } from './validation';
import { useI18n } from '../../i18n';

interface Props {
  languages: LanguageEntry[];
  onChange: (languages: LanguageEntry[]) => void;
}

const emptyLanguage: LanguageEntry = { name: '', proficiency: '' };

export const LanguagesSection: React.FC<Props> = ({ languages, onChange }) => {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [draft, setDraft] = useState<LanguageEntry>(emptyLanguage);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const proficiencyOptions = [
    { value: 'Native', label: t('proficiency.native') },
    { value: 'Full professional proficiency (C2)', label: t('proficiency.c2') },
    { value: 'Advanced (C1)', label: t('proficiency.c1') },
    { value: 'Intermediate (B2)', label: t('proficiency.b2') },
    { value: 'Basic (A2/B1)', label: t('proficiency.basic') },
  ];

  const openAdd = () => { setDraft(emptyLanguage); setErrors({}); setEditingIndex(null); setOpen(true); };
  const openEdit = (i: number) => { setDraft(languages[i]); setErrors({}); setEditingIndex(i); setOpen(true); };
  const remove = (i: number) => onChange(languages.filter((_, idx) => idx !== i));

  const submit = () => {
    const result = languageEntrySchema.safeParse(draft);
    if (!result.success) {
      const fieldErrors: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const key = issue.path[0];
        if (typeof key === 'string' && !fieldErrors[key]) fieldErrors[key] = issue.message;
      }
      setErrors(fieldErrors);
      return;
    }
    if (editingIndex == null) onChange([...languages, draft]);
    else onChange(languages.map((l, i) => (i === editingIndex ? draft : l)));
    setOpen(false);
  };

  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">{t('section.languages.title')}</h3>
          <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">{t('section.languages.hint')}</p>
        </div>
        <Button size="sm" variant="secondary" onClick={openAdd}>{t('languages.add')}</Button>
      </div>
      {languages.length === 0 ? (
        <p className="text-sm text-neutral-500 dark:text-neutral-400">{t('entries.none')}</p>
      ) : (
        <ul className="space-y-2">
          {languages.map((l, i) => (
            <li
              key={i}
              className="flex items-center justify-between gap-2 rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2 dark:border-neutral-800 dark:bg-neutral-800/50"
            >
              <span className="text-sm">
                <span className="font-semibold">{l.name}</span>
                {l.proficiency ? ` — ${l.proficiency}` : ''}
              </span>
              <div className="flex shrink-0 gap-2">
                <Button variant="link" size="xs" onClick={() => openEdit(i)}>{t('entry.edit')}</Button>
                <Button variant="danger" size="xs" onClick={() => remove(i)}>{t('entry.delete')}</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={editingIndex == null ? t('languages.add') : t('button.updateEntry')}
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>{t('button.cancel')}</Button>
            <Button variant="primary" onClick={submit}>
              {editingIndex == null ? t('button.addEntry') : t('button.updateEntry')}
            </Button>
          </>
        }
      >
        <div className="grid gap-4">
          <FormField label={t('placeholder.languageName')} required error={errors.name}>
            <Input
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              invalid={!!errors.name}
            />
          </FormField>
          <FormField label={t('field.proficiency')} required error={errors.proficiency}>
            <Select
              options={proficiencyOptions}
              value={draft.proficiency || 'Native'}
              onValueChange={(v) => setDraft((d) => ({ ...d, proficiency: v }))}
            />
          </FormField>
        </div>
      </Dialog>
    </div>
  );
};
