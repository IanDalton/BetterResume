import React, { useState, useEffect } from 'react';
import { ResumeEntry, EntryType } from '../types';

interface EntryBuilderProps {
  entries: ResumeEntry[];
  onAdd: (e: ResumeEntry) => void;
  onUpdate: (i: number, e: ResumeEntry) => void;
  onRemove: (i: number) => void;
}

const emptyEntry: ResumeEntry = { type: 'job', role: '', company: '', location: '', start: '', end: '', description: '', role_description: '' };

export const EntryBuilder: React.FC<EntryBuilderProps> = ({ entries, onAdd, onUpdate, onRemove }) => {
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
    if (form.type !== 'info' && !form.role) return;
    editing == null ? onAdd(form) : onUpdate(editing, form);
    reset();
  };

  const startEdit = (i: number) => { setEditing(i); setForm(entries[i]); };

  const showJobFields = form.type !== 'info';
  const showRoleDesc = form.type === 'info' && form.role === 'website';

  return (
    <section className="mb-12">
      <h2 className="text-xl font-semibold mb-4">Add Entry</h2>
      <form onSubmit={submit} className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 bg-neutral-900/60 border border-neutral-800 rounded p-4">
        <SelectField label="Type" value={form.type} onChange={v => setField('type', v as EntryType)} options={[
          ['info','Personal Info'],['education','Education'],['job','Job'],['non-profit','Non-Profit'],['project','Project'],['contract','Contract'],['part-time','Part-Time']
        ]} />
        {showJobFields && <InputField label="Company" value={form.company||''} onChange={v=>setField('company',v)} placeholder="Acme Corp" />}
        {showJobFields && <InputField label="Location" value={form.location||''} onChange={v=>setField('location',v)} placeholder="City, Country" />}
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase tracking-wide text-neutral-400">Role / Field</label>
          {form.type === 'info' ? (
            <select className="bg-neutral-800 border border-neutral-700 rounded px-2 py-2 text-sm" value={form.role} onChange={e => setField('role', e.target.value)}>
              {['name','email','phone','website','address'].map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          ) : (
            <input className="bg-neutral-800 border border-neutral-700 rounded px-2 py-2 text-sm" value={form.role} onChange={e => setField('role', e.target.value)} placeholder="Role" />
          )}
        </div>
        {showJobFields && <InputField label="Start" value={form.start||''} onChange={v=>setField('start',v)} placeholder="MM/YYYY" />}
        {showJobFields && <InputField label="End" value={form.end||''} onChange={v=>setField('end',v)} placeholder="MM/YYYY or Present" />}
  <TextareaField label="Description" value={form.description||''} onChange={v=>setField('description',v)} placeholder="Details..." className="md:col-span-2 lg:col-span-3" />
        {showRoleDesc && <TextareaField label="Extra Details" value={form.role_description||''} onChange={v=>setField('role_description',v)} placeholder="When applicable..." className="md:col-span-2 lg:col-span-3" />}
        <div className="md:col-span-2 lg:col-span-3 flex justify-end gap-3 pt-2">
          {editing != null && <button type="button" onClick={reset} className="px-4 py-2 rounded bg-neutral-700 hover:bg-neutral-600 text-sm">Cancel</button>}
          <button type="submit" className="px-4 py-2 rounded bg-red-600 hover:bg-red-500 text-sm font-medium">{editing == null ? 'Add Entry' : 'Update Entry'}</button>
        </div>
      </form>
      <EntriesList entries={entries} onEdit={startEdit} onRemove={onRemove} />
    </section>
  );
};

interface EntriesListProps { entries: ResumeEntry[]; onEdit: (i:number)=>void; onRemove:(i:number)=>void }
export const EntriesList: React.FC<EntriesListProps> = ({ entries, onEdit, onRemove }) => {
  if (!entries.length) return <p className="text-sm text-neutral-500">No entries yet.</p>;
  return (
    <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {entries.map((e,i) => {
        const isInfo = e.type === 'info';
        return (
          <div key={i} className={(isInfo? 'bg-blue-600/20 border-blue-600/40':'bg-neutral-800/70 border-neutral-700') + ' border rounded-xl p-4 flex flex-col gap-2 relative'}>
            <div className="text-xs uppercase tracking-wide text-neutral-400 flex justify-between items-center">
              <span>{e.type}</span>
              <div className="flex gap-2">
                <button onClick={()=>onEdit(i)} className="text-indigo-400 hover:text-indigo-300 text-xs">Edit</button>
                <button onClick={()=>onRemove(i)} className="text-red-400 hover:text-red-300 text-xs">Del</button>
              </div>
            </div>
            <div className="space-y-1 text-sm">
              <p className="font-semibold">{e.role}{e.company? ' @ '+e.company: ''}</p>
              {e.location && <p className="text-neutral-400">{e.location}</p>}
              {(e.start || e.end) && <p className="text-neutral-500 text-xs">{e.start || '—'} → {e.end || 'Present'}</p>}
              {e.description && <p className="text-neutral-300 whitespace-pre-wrap text-xs leading-relaxed">{e.description}</p>}
              {e.role_description && <p className="text-neutral-400 italic text-xs whitespace-pre-wrap">{e.role_description}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
};

// Reusable field components
const baseInput = 'bg-neutral-800 border border-neutral-700 rounded px-2 py-2 text-sm focus:outline-none focus:ring focus:ring-indigo-500';
const labelCls = 'text-xs uppercase tracking-wide text-neutral-400';

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
