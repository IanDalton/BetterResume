import React, { useState } from 'react';
import { ResumeEntry, EntryType } from '../types';
import { useI18n } from '../i18n';

interface WizardProps {
  entries: ResumeEntry[];
  addEntry: (e: ResumeEntry) => void;
  updateEntry: (i:number, e:ResumeEntry) => void;
  removeEntry: (i:number) => void;
  onFinish: () => void;
}

// Steps: personal -> education -> experience -> review
// Personal collects: name, email, phone, website, address
// Education: one or more education + certification entries
// Experience: add other types
// Review: simple summary + Finish

export const OnboardingWizard: React.FC<WizardProps> = ({ entries, addEntry, updateEntry, removeEntry, onFinish }) => {
  const { t } = useI18n();
  const [step, setStep] = useState<number>(0);

  const personalEntries = entries.filter(e=>e.type==='info');
  const educationEntries = entries.filter(e=>e.type==='education' || e.type==='certification');
  const experienceEntries = entries.filter(e=> !['info','education','certification'].includes(e.type));

  const nextAllowed = () => {
    if (step === 0) {
      const roles = personalEntries.map(e=>e.role);
      return roles.includes('name') && roles.includes('email');
    }
    if (step === 1) return educationEntries.length > 0; // require at least one
    if (step === 2) return experienceEntries.length > 0; // at least one experience
    return true;
  };

  const goNext = () => { if (nextAllowed()) setStep(s=>s+1); };
  const goBack = () => setStep(s=> Math.max(0,s-1));

  return (
    <div className="space-y-8">
      <WizardProgress step={step} />
  {step === 0 && <PersonalStep addEntry={addEntry} existing={personalEntries} updateEntry={updateEntry} removeEntry={removeEntry} entries={entries} />}
      {step === 1 && <EducationStep addEntry={addEntry} existing={educationEntries} updateEntry={updateEntry} />}
      {step === 2 && <ExperienceStep addEntry={addEntry} existing={experienceEntries} updateEntry={updateEntry} />}
      {step === 3 && <ReviewStep all={entries} onFinish={onFinish} />}

      <div className="flex justify-between items-center pt-4 border-t border-neutral-800">
  {step>0 ? <button onClick={goBack} className="btn-secondary">Back</button> : <span />}
  {step<3 && <button disabled={!nextAllowed()} onClick={goNext} className="btn-primary disabled:opacity-40">Next</button>}
      </div>
    </div>
  );
};

const WizardProgress: React.FC<{step:number}> = ({ step }) => {
  const stages = ['Personal','Education','Experience','Review'];
  return (
    <ol className="flex gap-4 text-xs uppercase tracking-wide text-neutral-500">
      {stages.map((s,i)=> (
  <li key={s} className={"flex items-center gap-1 "+(i===step? 'text-white':'')}> <span className="w-6 h-6 rounded-full border border-neutral-600 flex items-center justify-center text-[10px]" style={{background:i<=step? '#b91c1c':'transparent'}}>{i+1}</span>{s}</li>
      ))}
    </ol>
  );
};

// Reusable small add form components per category to keep simpler than full EntryBuilder
const PersonalStep: React.FC<{ addEntry:(e:ResumeEntry)=>void; existing:ResumeEntry[]; updateEntry:(i:number,e:ResumeEntry)=>void; removeEntry:(i:number)=>void; entries:ResumeEntry[] }> = ({ addEntry, existing, updateEntry, removeEntry, entries }) => {
  const personalSingles: Array<{role:string; label:string}> = [
    {role:'name',label:'Full Name'},
    {role:'email',label:'Email'},
    {role:'phone',label:'Phone'},
    {role:'address',label:'Location'}
  ];
  const websites = existing.filter(e=>e.role==='website');
  const siteKinds = ['portfolio','github','linkedin','twitter','blog','other'] as const;
  const setValue = (role:string, value:string) => {
    const idx = entries.findIndex(e=> e.type==='info' && e.role===role);
    if (idx>=0) updateEntry(idx, { ...entries[idx], description: value });
    else addEntry({ type:'info', role: role, description: value });
  };
  const addWebsite = (url:string, kind:string, customLabel?:string) => {
    if (!url.trim()) return;
    const label = kind === 'other' ? (customLabel?.trim() || 'other') : kind;
    addEntry({ type:'info', role:'website', description: url.trim(), role_description: label });
  };
  const updateWebsiteUrl = (i:number, url:string) => {
    const entry = websites[i];
    const globalIdx = entries.indexOf(entry);
    if (globalIdx>=0) updateEntry(globalIdx, { ...entry, description:url });
  };
  const updateWebsiteKind = (i:number, kind:string) => {
    const entry = websites[i];
    const globalIdx = entries.indexOf(entry);
    const label = kind === 'other' ? (entry.role_description || 'other') : kind;
    if (globalIdx>=0) updateEntry(globalIdx, { ...entry, role_description: label });
  }
  const updateWebsiteCustomLabel = (i:number, custom:string) => {
    const entry = websites[i];
    const globalIdx = entries.indexOf(entry);
    if (globalIdx>=0) updateEntry(globalIdx, { ...entry, role_description: custom });
  }
  const removeWebsite = (i:number) => {
    const entry = websites[i];
    const globalIdx = entries.indexOf(entry);
    if (globalIdx>=0) removeEntry(globalIdx);
  };
  const [newSite, setNewSite] = React.useState('');
  const [newKind, setNewKind] = React.useState<string>('portfolio');
  const [newCustom, setNewCustom] = React.useState('');
  return (
    <div className="space-y-8">
      <div className="grid gap-6 md:grid-cols-2">
        {personalSingles.map(pr => {
          const entry = existing.find(e=>e.role===pr.role);
          return (
            <div key={pr.role} className="flex flex-col gap-1">
              <label className="text-xs uppercase tracking-wide text-neutral-400">{pr.label}</label>
              <input className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={entry?.description||''} onChange={e=>setValue(pr.role,e.target.value)} placeholder={pr.label} />
            </div>
          );
        })}
      </div>
      <div className="space-y-3">
        <label className="text-xs uppercase tracking-wide text-neutral-400 block">Websites / Profiles</label>
        <div className="flex flex-col md:flex-row gap-2">
          <div className="flex gap-2 flex-1">
            <select className="bg-neutral-800 border border-neutral-700 rounded px-2 py-2 text-sm" value={newKind} onChange={e=>{ setNewKind(e.target.value); if (e.target.value!=='other') setNewCustom(''); }}>
              {siteKinds.map(k=> <option key={k} value={k}>{k}</option>)}
            </select>
            {newKind==='other' && <input className="w-32 bg-neutral-800 border border-neutral-700 rounded px-2 py-2 text-sm" placeholder="Label" value={newCustom} onChange={e=>setNewCustom(e.target.value)} />}
            <input className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" placeholder="https://..." value={newSite} onChange={e=>setNewSite(e.target.value)} onKeyDown={e=>{ if (e.key==='Enter'){ e.preventDefault(); addWebsite(newSite, newKind, newCustom); setNewSite(''); } }} />
          </div>
          <button type="button" onClick={()=>{ addWebsite(newSite, newKind, newCustom); setNewSite(''); }} className="btn-primary btn-sm self-start">Add</button>
        </div>
        {websites.length>0 && (
          <ul className="space-y-2 text-sm">
            {websites.map((w,i)=>(
              <li key={i} className="flex flex-col gap-2 bg-neutral-800/60 border border-neutral-700 rounded p-3">
                <div className="flex flex-wrap gap-2 items-center">
                  <select className="bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-xs" value={deriveKindValue(w.role_description)} onChange={e=>updateWebsiteKind(i,e.target.value)}>
                    {siteKinds.map(k=> <option key={k} value={k}>{k}</option>)}
                  </select>
                  {deriveKindValue(w.role_description)==='other' && (
                    <input className="bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-xs" placeholder="Label" value={w.role_description||''} onChange={e=>updateWebsiteCustomLabel(i,e.target.value)} />
                  )}
                  <input className="flex-1 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-xs" value={w.description||''} onChange={e=>updateWebsiteUrl(i,e.target.value)} />
                  <button type="button" onClick={()=>removeWebsite(i)} className="text-red-400 hover:text-red-300 text-[11px]">Remove</button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="text-[11px] text-neutral-500">Add as many personal / professional links as you like (portfolio, GitHub, LinkedIn, etc.). Each link can have its own label.</p>
      </div>
    </div>
  );
};

// Helper to map stored label to selection value
function deriveKindValue(label?: string) {
  if (!label) return 'other';
  const normalized = label.toLowerCase();
  if (['portfolio','github','linkedin','twitter','blog'].includes(normalized)) return normalized;
  return 'other';
}

const EducationStep: React.FC<{ addEntry:(e:ResumeEntry)=>void; existing:ResumeEntry[]; updateEntry:(i:number,e:ResumeEntry)=>void }> = ({ addEntry, existing, updateEntry }) => {
  const [form, setForm] = useState<ResumeEntry>({ type:'education', role:'', company:'', location:'', start:'', end:'', description:'' });
  const submit = (e:React.FormEvent) => { e.preventDefault(); addEntry(form); setForm({ ...form, role:'', company:'', location:'', start:'', end:'', description:'' }); };
  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-2 bg-neutral-900/60 border border-neutral-800 rounded p-4">
        <input required placeholder="Degree / Program" className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.role} onChange={e=>setForm(f=>({...f, role:e.target.value}))} />
        <input required placeholder="Institution" className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.company} onChange={e=>setForm(f=>({...f, company:e.target.value}))} />
        <input placeholder="Location" className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.location} onChange={e=>setForm(f=>({...f, location:e.target.value}))} />
        <div className="flex gap-2">
          <input placeholder="Start" className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.start} onChange={e=>setForm(f=>({...f, start:e.target.value}))} />
          <input placeholder="End / Present" className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.end} onChange={e=>setForm(f=>({...f, end:e.target.value}))} />
        </div>
        <textarea placeholder="Description / Achievements" className="md:col-span-2 bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm min-h-[80px]" value={form.description} onChange={e=>setForm(f=>({...f, description:e.target.value}))} />
        <div className="md:col-span-2 flex justify-end">
          <button className="btn-primary">Add Education</button>
        </div>
      </form>
      <ul className="space-y-2">
        {existing.map((e,i)=>(
          <li key={i} className="text-sm flex justify-between bg-neutral-800/60 border border-neutral-700 rounded px-3 py-2">
            <span>{e.role} @ {e.company}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

const ExperienceStep: React.FC<{ addEntry:(e:ResumeEntry)=>void; existing:ResumeEntry[]; updateEntry:(i:number,e:ResumeEntry)=>void }> = ({ addEntry, existing, updateEntry }) => {
  const [form, setForm] = useState<ResumeEntry>({ type:'job', role:'', company:'', location:'', start:'', end:'', description:'' });
  const submit = (e:React.FormEvent) => { e.preventDefault(); addEntry(form); setForm({ ...form, role:'', company:'', location:'', start:'', end:'', description:'' }); };
  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-2 bg-neutral-900/60 border border-neutral-800 rounded p-4">
        <select className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.type} onChange={e=>setForm(f=>({...f, type: e.target.value as EntryType}))}>
          {['job','project','contract','part-time','non-profit'].map(t=> <option key={t} value={t}>{t}</option>)}
        </select>
        <input required placeholder="Role / Title" className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.role} onChange={e=>setForm(f=>({...f, role:e.target.value}))} />
        <input placeholder="Company / Org" className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.company} onChange={e=>setForm(f=>({...f, company:e.target.value}))} />
        <input placeholder="Location" className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.location} onChange={e=>setForm(f=>({...f, location:e.target.value}))} />
        <div className="flex gap-2">
          <input placeholder="Start" className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.start} onChange={e=>setForm(f=>({...f, start:e.target.value}))} />
          <input placeholder="End / Present" className="flex-1 bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" value={form.end} onChange={e=>setForm(f=>({...f, end:e.target.value}))} />
        </div>
        <textarea placeholder="Description / Impact" className="md:col-span-2 bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm min-h-[80px]" value={form.description} onChange={e=>setForm(f=>({...f, description:e.target.value}))} />
        <div className="md:col-span-2 flex justify-end">
          <button className="btn-primary">Add Experience</button>
        </div>
      </form>
      <ul className="space-y-2">
        {existing.map((e,i)=>(
          <li key={i} className="text-sm flex justify-between bg-neutral-800/60 border border-neutral-700 rounded px-3 py-2">
            <span>{e.role}{e.company? ' @ '+e.company: ''}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

const ReviewStep: React.FC<{ all:ResumeEntry[]; onFinish:()=>void }> = ({ all, onFinish }) => {
  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold">Review</h3>
      <p className="text-sm text-neutral-400">Quick summary of what you've added. You can finish to access full dashboard and make further edits.</p>
      <div className="bg-neutral-900 border border-neutral-800 rounded p-4 max-h-80 overflow-auto text-xs space-y-2">
        {all.map((e,i)=>(
          <div key={i} className="border-b border-neutral-800 pb-2 last:border-b-0">
            <p className="font-medium">{e.type}: {e.role}{e.company? ' @ '+e.company: ''}</p>
            {e.description && <p className="text-neutral-400 whitespace-pre-wrap">{e.description}</p>}
          </div>
        ))}
      </div>
  <button onClick={onFinish} className="btn-primary">Finish Onboarding</button>
    </div>
  );
};
