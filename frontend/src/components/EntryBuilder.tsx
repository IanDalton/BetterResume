import React, { useState, useEffect } from 'react';
import { ResumeEntry, EntryType } from '../types';
import { useI18n } from '../i18n';
import { FormField, Input, Textarea, Select, Button } from './ui';

interface EntryBuilderProps {
  entries: ResumeEntry[];
  onAdd: (e: ResumeEntry) => void;
  onUpdate: (i: number, e: ResumeEntry) => void;
  onRemove: (i: number) => void;
}

const emptyEntry: ResumeEntry = { type: 'info', role: '', company: '', location: '', start: '', end: '', description: '', role_description: '' };

export const EntryBuilder: React.FC<EntryBuilderProps> = ({ entries, onAdd, onUpdate, onRemove }) => {
  const { t } = useI18n();
  const [form, setForm] = useState<ResumeEntry>(emptyEntry);
  const [editing, setEditing] = useState<number | null>(null);

  const setField = (k: keyof ResumeEntry, v: string) => setForm(p => ({ ...p, [k]: v }));
  const reset = () => {
    setForm(f => ({ ...emptyEntry, type: f.type }));
    setEditing(null);
  };

  // Ensure a default role when switching to personal info
  useEffect(() => {
    if (form.type === 'info' && !form.role) {
      setForm(f => ({ ...f, role: 'name' }));
    }
  }, [form.type, form.role]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    // Require role only for non-info entries (info role auto-populated)
    if (form.type !== 'info' && form.type !== 'education' && !form.role) return;
    // Languages need an explicit proficiency level
    if (form.type === 'language' && !form.description) return;
    editing == null ? onAdd(form) : onUpdate(editing, form);
    reset();
  };

  const startEdit = (i: number) => { setEditing(i); setForm(entries[i]); };

  const isLanguage = form.type === 'language';
  const showJobFields = form.type !== 'info' && !isLanguage;
  const showRoleDesc = form.type === 'info' && form.role === 'website';

  const proficiencyLevels: [string, string][] = [
    ['Native', t('proficiency.native')],
    ['Full professional proficiency (C2)', t('proficiency.c2')],
    ['Advanced (C1)', t('proficiency.c1')],
    ['Intermediate (B2)', t('proficiency.b2')],
    ['Basic (A2/B1)', t('proficiency.basic')],
  ];

  const typeOptions = [
    { value: 'info', label: t('type.info') },
    { value: 'education', label: t('type.education') },
    { value: 'job', label: t('type.job') },
    { value: 'non-profit', label: t('type.non-profit') },
    { value: 'project', label: t('type.project') },
    { value: 'contract', label: t('type.contract') },
    { value: 'part-time', label: t('type.part-time') },
    { value: 'language', label: t('type.language') },
  ];
  const personalFieldOptions = ['name','email','phone','website','address'].map(r => ({ value: r, label: t('field.personal.'+r) }));
  const proficiencyOptions = [{ value: '__unset__', label: t('proficiency.select') }, ...proficiencyLevels.map(([value, label]) => ({ value, label }))];

  return (
    <section className="mb-12">
      <h2 className="text-xl font-semibold mb-4">{t('add.entry.section')}</h2>
  <form onSubmit={submit} className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 bg-neutral-50 border border-neutral-200 rounded p-4 dark:bg-neutral-900/60 dark:border-neutral-800">
        <FormField label={t('field.type')}>
          <Select options={typeOptions} value={form.type} onValueChange={v => setField('type', v as EntryType)} />
        </FormField>
        {showJobFields && (
          <FormField label={t('field.company')}>
            <Input value={form.company||''} onChange={e=>setField('company',e.target.value)} placeholder={t('placeholder.company')} />
          </FormField>
        )}
        {showJobFields && (
          <FormField label={t('field.location')}>
            <Input value={form.location||''} onChange={e=>setField('location',e.target.value)} placeholder={t('placeholder.location')} />
          </FormField>
        )}
        {form.type !== 'education' && (
          <FormField label={t('field.role')}>
            {form.type === 'info' ? (
              <Select options={personalFieldOptions} value={form.role} onValueChange={v => setField('role', v)} />
            ) : (
              <Input value={form.role} onChange={e => setField('role', e.target.value)} placeholder={isLanguage ? t('placeholder.languageName') : t('placeholder.role')} />
            )}
          </FormField>
        )}
        {showJobFields && (
          <FormField label={t('field.start')}>
            <Input value={form.start||''} onChange={e=>setField('start',e.target.value)} placeholder={t('placeholder.start')} />
          </FormField>
        )}
        {showJobFields && (
          <FormField label={t('field.end')}>
            <Input value={form.end||''} onChange={e=>setField('end',e.target.value)} placeholder={t('placeholder.end')} />
          </FormField>
        )}
        {isLanguage ? (
          <FormField label={t('field.proficiency')}>
            <Select options={proficiencyOptions} value={form.description || '__unset__'} onValueChange={v => setField('description', v === '__unset__' ? '' : v)} />
          </FormField>
        ) : (
          <FormField label={t('field.description')} className="md:col-span-2 lg:col-span-3">
            <Textarea value={form.description||''} onChange={e=>setField('description',e.target.value)} placeholder={t('placeholder.description')} />
          </FormField>
        )}
        {showRoleDesc && (
          <FormField label={t('field.extraDetails')} className="md:col-span-2 lg:col-span-3">
            <Textarea value={form.role_description||''} onChange={e=>setField('role_description',e.target.value)} placeholder={t('placeholder.extraDetails')} />
          </FormField>
        )}
        <div className="md:col-span-2 lg:col-span-3 flex justify-end gap-3 pt-2">
          {editing != null && <Button type="button" variant="secondary" onClick={reset}>{t('button.cancel')}</Button>}
          <Button type="submit" variant="secondary">{editing == null ? t('button.addEntry') : t('button.updateEntry')}</Button>
        </div>
      </form>
      <EntriesList entries={entries} onEdit={startEdit} onRemove={onRemove} />
    </section>
  );
};

interface EntriesListProps { entries: ResumeEntry[]; onEdit: (i:number)=>void; onRemove:(i:number)=>void }
export const EntriesList: React.FC<EntriesListProps> = ({ entries, onEdit, onRemove }) => {
  const { t } = useI18n();
  if (!entries.length) return <p className="text-sm text-neutral-500">{t('entries.none')}</p>;
  return (
    <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {entries.map((e,i) => {
        const isInfo = e.type === 'info';
        return (
          <div key={i} className={(isInfo? 'bg-red-600/10 border-red-600/30':'bg-neutral-100 dark:bg-neutral-800/70 border-neutral-200 dark:border-neutral-700') + ' border rounded-xl p-4 flex flex-col gap-2 relative'}>
            <div className="text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400 flex justify-between items-center">
              <span>{e.type}</span>
              <div className="flex gap-2">
                <button onClick={()=>onEdit(i)} className="btn-link-primary text-xs">{t('entry.edit')}</button>
                <button onClick={()=>onRemove(i)} className="btn-danger text-xs">{t('entry.delete')}</button>
              </div>
            </div>
            <div className="space-y-1 text-sm">
              <p className="font-semibold">{e.role}{e.company? ' @ '+e.company: ''}</p>
              {e.location && <p className="text-neutral-600 dark:text-neutral-400">{e.location}</p>}
              {(e.start || e.end) && <p className="text-neutral-500 text-xs">{e.start || '—'} → {e.end || t('present')}</p>}
              {e.description && <p className="text-neutral-700 dark:text-neutral-300 whitespace-pre-wrap text-xs leading-relaxed">{e.description}</p>}
              {e.role_description && <p className="text-neutral-600 dark:text-neutral-400 italic text-xs whitespace-pre-wrap">{e.role_description}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
};

