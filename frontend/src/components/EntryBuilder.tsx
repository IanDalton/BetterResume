import React, { useState, useEffect } from 'react';
import { ResumeEntry, EntryType } from '../types';
import { useI18n } from '../i18n';

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
    editing == null ? onAdd(form) : onUpdate(editing, form);
    reset();
  };

  const startEdit = (i: number) => { setEditing(i); setForm(entries[i]); };

  const showJobFields = form.type !== 'info';
  const showRoleDesc = form.type === 'info' && form.role === 'website';

  return (
    <section className="mb-12">
      <h2 className="text-xl font-semibold mb-4">{t('add.entry.section')}</h2>
  <form onSubmit={submit} className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 bg-neutral-50 border border-neutral-200 rounded p-4 dark:bg-neutral-900/60 dark:border-neutral-800">
        <SelectField label={t('field.type')} value={form.type} onChange={v => setField('type', v as EntryType)} options={[
          ['info',t('type.info')],['education',t('type.education')],['job',t('type.job')],['non-profit',t('type.non-profit')],['project',t('type.project')],['contract',t('type.contract')],['part-time',t('type.part-time')]
        ]} />
        {showJobFields && <InputField label={t('field.company')} value={form.company||''} onChange={v=>setField('company',v)} placeholder={t('placeholder.company')} />}
        {showJobFields && <InputField label={t('field.location')} value={form.location||''} onChange={v=>setField('location',v)} placeholder={t('placeholder.location')} />}
        {form.type !== 'education' && (
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400">{t('field.role')}</label>
            {form.type === 'info' ? (
              <select className="bg-white dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded px-2 py-2 text-sm" value={form.role} onChange={e => setField('role', e.target.value)}>
                {['name','email','phone','website','address'].map(r => <option key={r} value={r}>{t('field.personal.'+r)}</option>)}
              </select>
            ) : (
              <input className="bg-white dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded px-2 py-2 text-sm" value={form.role} onChange={e => setField('role', e.target.value)} placeholder={t('placeholder.role')} />
            )}
          </div>
        )}
        {showJobFields && <InputField label={t('field.start')} value={form.start||''} onChange={v=>setField('start',v)} placeholder={t('placeholder.start')} />}
        {showJobFields && <InputField label={t('field.end')} value={form.end||''} onChange={v=>setField('end',v)} placeholder={t('placeholder.end')} />}
  <TextareaField label={t('field.description')} value={form.description||''} onChange={v=>setField('description',v)} placeholder={t('placeholder.description')} className="md:col-span-2 lg:col-span-3" />
        {showRoleDesc && <TextareaField label={t('field.extraDetails')} value={form.role_description||''} onChange={v=>setField('role_description',v)} placeholder={t('placeholder.extraDetails')} className="md:col-span-2 lg:col-span-3" />}
        <div className="md:col-span-2 lg:col-span-3 flex justify-end gap-3 pt-2">
          {editing != null && <button type="button" onClick={reset} className="btn-secondary">{t('button.cancel')}</button>}
          <button type="submit" className="btn-primary">{editing == null ? t('button.addEntry') : t('button.updateEntry')}</button>
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

// Reusable field components
const baseInput = 'bg-white dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded px-2 py-2 text-sm focus:outline-none focus:ring focus:ring-red-500';
const labelCls = 'text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400';

const InputField: React.FC<{label:string; value:string; onChange:(v:string)=>void; placeholder?:string;}> = ({label,value,onChange,placeholder}) => (
  <div className="flex flex-col gap-1">
    <label className={labelCls}>{label}</label>
    <input className={baseInput} value={value} placeholder={placeholder} onChange={e=>onChange(e.target.value)} />
  </div>
);

const TextareaField: React.FC<{label:string; value:string; onChange:(v:string)=>void; placeholder?:string; className?:string;}> = ({label,value,onChange,placeholder,className}) => (
  <div className={"flex flex-col gap-1 "+(className||'')}>
    <label className={labelCls}>{label}</label>
    <textarea className={baseInput+" min-h-[100px] resize-y"} value={value} placeholder={placeholder} onChange={e=>onChange(e.target.value)} />
  </div>
);

const SelectField: React.FC<{label:string; value:string; onChange:(v:string)=>void; options:[string,string][];}> = ({label,value,onChange,options}) => (
  <div className="flex flex-col gap-1">
    <label className={labelCls}>{label}</label>
    <select className={baseInput} value={value} onChange={e=>onChange(e.target.value)}>
      {options.map(([val,lab])=> <option key={val} value={val}>{lab}</option>)}
    </select>
  </div>
);
