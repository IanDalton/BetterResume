import React, { useState, useEffect, useCallback } from 'react';
// Use explicit relative path so Vite resolves without custom alias
import { uploadJobsCsv, generateResumeStream, buildCsvFromEntries } from './services';
import { ResumeEntry } from './types';
import { EntryBuilder } from './components/EntryBuilder';
import { AuthGate, UserBar } from './components/AuthGate';
import { logout, loadUserData, saveUserData } from './services/firebase';
import { useI18n, availableLanguages } from './i18n';

const DEFAULT_MODEL = 'gemini-2.5-flash';


export default function App() {
  const { t, lang, setLang } = useI18n();
  const [entries, setEntries] = useState<ResumeEntry[]>(() => {
    try { const raw = localStorage.getItem('br.entries'); if (raw) return JSON.parse(raw); } catch {}
    return [];
  });
  const [user, setUser] = useState<{mode:'auth'|'guest'; uid:string; email?:string} | null>(null);
  const [authGateOpenSignal, setAuthGateOpenSignal] = useState(0);
  const userId = user?.uid || 'guest';
  const [loading, setLoading] = useState(false);
  const [resumeJson, setResumeJson] = useState<any>(null);
  const [downloadLinks, setDownloadLinks] = useState<{pdf:string; source:string}|null>(null);
  const [jobDescription, setJobDescription] = useState(() => {
    try { return localStorage.getItem('br.jobDescription') || ''; } catch { return ''; }
  });
  const [format, setFormat] = useState<'latex' | 'word'>(() => {
    try { const f = localStorage.getItem('br.format'); if (f === 'word' || f === 'latex') return f; } catch {}
    return 'latex';
  });
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{stage:string; message?:string}[]>([]);

  // Persist state to localStorage (debounced minimal by relying on React batch)
  useEffect(() => { try { localStorage.setItem('br.entries', JSON.stringify(entries)); } catch {} }, [entries]);
  // Hydrate from Firestore via AuthGate callback (legacy effect removed)

  // Removed continuous auto-save; persistence now triggered only on explicit upload.
  // no longer store userId directly; guests stored inside AuthGate logic
  useEffect(() => { try { localStorage.setItem('br.jobDescription', jobDescription); } catch {} }, [jobDescription]);
  useEffect(() => { try { localStorage.setItem('br.format', format); } catch {} }, [format]);

  const addEntry = (entry: ResumeEntry) => setEntries(p => [...p, entry]);
  const updateEntry = (index: number, entry: ResumeEntry) => setEntries(p => p.map((e,i)=> i===index? entry : e));
  const removeEntry = (index: number) => setEntries(p => p.filter((_,i)=> i!==index));

  const handleUpload = async () => {
    try {
      setError(null);
      setLoading(true);
  const csv = buildCsvFromEntries(entries);
      const blob = new Blob([csv], { type: 'text/csv' });
      const file = new File([blob], 'jobs.csv', { type: 'text/csv' });
      await uploadJobsCsv(userId, file);
      if (user?.mode === 'auth') {
        // Persist current state to Firestore after successful upload
        saveUserData(user.uid, { entries, jobDescription, format }).catch(()=>{});
      }
      alert('Jobs uploaded');
    } catch (e: any) {
      setError(e.message || 'Upload failed');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    try {
      setError(null);
      setLoading(true);
      setProgress([]);
  const res = await generateResumeStream(userId, {
        job_description: jobDescription,
        format,
        model: DEFAULT_MODEL
      }, evt => {
        setProgress(p => [...p, {stage: evt.stage, message: evt.message}]);
      });
  setResumeJson(res.result);
  if (res.files) setDownloadLinks(res.files);
    } catch (e: any) {
      setError(e.message || 'Generation failed');
    } finally {
      setLoading(false);
    }
  };

  const clearAll = () => {
    if (!confirm(t('confirm.clear'))) return;
    try {
      localStorage.removeItem('br.entries');
    localStorage.removeItem('br.guestId');
      localStorage.removeItem('br.jobDescription');
      localStorage.removeItem('br.format');
    } catch {}
    setEntries([]);
  setUser(null);
    setJobDescription('');
    setFormat('latex');
    setResumeJson(null);
    setError(null);
  };

  return (
    <div className="max-w-5xl mx-auto p-4 font-sans relative">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t('app.title')}</h1>
          <p className="text-sm text-neutral-400">{t('app.tagline')}</p>
        </div>
        <div className="flex gap-4 items-center">
          {user && <UserBar user={user} onLogout={async ()=>{
  await logout();
  setUser(null);
  setEntries([]);
  setJobDescription('');
  setFormat('latex');
}} onSignInRequest={() => {
  // Guest wants to upgrade to account: keep cache, remove guest id and open auth modal
  if (user.mode === 'guest') {
    try { localStorage.removeItem('br.guestId'); } catch {}
    setAuthGateOpenSignal(s=>s+1);
  }
}} />}
          <label className="text-sm flex flex-col">{t('format')}
            <select className="mt-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-sm" value={format} onChange={e => setFormat(e.target.value as any)}>
              <option value='latex'>LaTeX</option>
              <option value='word'>Word</option>
            </select>
          </label>
          <label className="text-sm flex flex-col">Lang
            <select className="mt-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-sm" value={lang} onChange={e => setLang(e.target.value as any)}>
              {availableLanguages.map(l => <option key={l.code} value={l.code}>{t(l.labelKey)}</option>)}
            </select>
          </label>
        </div>
      </header>
  <EntryBuilder entries={entries} onAdd={addEntry} onUpdate={updateEntry} onRemove={removeEntry} />

      <section className="space-y-4 mb-12">
        <h2 className="text-xl font-semibold">{t('job.description.section')}</h2>
        <textarea className="w-full min-h-[200px] bg-neutral-900 border border-neutral-800 rounded p-3 text-sm resize-y focus:outline-none focus:ring focus:ring-indigo-500" value={jobDescription} onChange={e => setJobDescription(e.target.value)} placeholder={t('job.description.placeholder')} />
        <div className="flex flex-wrap gap-2">
          <button className="px-3 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm" disabled={!entries.some(e=>e.type!== 'info') || loading} onClick={handleUpload}>{t('upload.jobs')}</button>
          <button className="px-3 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm" disabled={loading || !jobDescription} onClick={handleGenerate}>{t('generate.resume')}</button>
          <button type="button" className="px-3 py-2 rounded bg-neutral-700 hover:bg-neutral-600 text-sm" onClick={clearAll}>{t('button.clear')}</button>
        </div>
        {loading && <p className="text-sm text-neutral-400">{t('working')}</p>}
        {progress.length>0 && (
          <ul className="text-xs text-neutral-400 space-y-1 bg-neutral-900 border border-neutral-800 rounded p-2 max-h-48 overflow-auto">
            {progress.map((p,i)=>(<li key={i}><span className="font-mono text-neutral-500">{i+1}.</span> {p.stage}{p.message?`: ${p.message}`:''}</li>))}
          </ul>
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}
        {resumeJson && (
          <div className="mt-6 space-y-3 bg-neutral-900 border border-neutral-800 rounded p-4">
            <h3 className="text-lg font-semibold">Generated Resume JSON</h3>
            <pre className="text-xs overflow-auto max-h-96 bg-neutral-950 p-3 rounded border border-neutral-800">{JSON.stringify(resumeJson, null, 2)}</pre>
            {downloadLinks && (
              <div className="flex gap-4 flex-wrap text-sm">
                <a className="text-indigo-400 hover:underline" href={downloadLinks.pdf} target="_blank" rel="noreferrer">Download PDF</a>
                <a className="text-indigo-400 hover:underline" href={downloadLinks.source} target="_blank" rel="noreferrer">Download Source</a>
              </div>
            )}
          </div>
        )}
    </section>
  <AuthGate forceOpenSignal={authGateOpenSignal} onResolved={useCallback((u, data) => {
      setUser(u);
      if (data) {
        if (Array.isArray(data.entries)) setEntries(data.entries as any);
        if (data.jobDescription) setJobDescription(data.jobDescription);
        if (data.format === 'latex' || data.format === 'word') setFormat(data.format);
      }
    }, [])} />
  </div>
  );
}

// Legacy interface (used by csv util older function). Safe to remove if unused.
export interface JobRecord { title: string; company: string; startDate: string; endDate: string; description: string; }
