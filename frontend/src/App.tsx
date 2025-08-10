import React, { useState } from 'react';
import { uploadJobsCsv,generateResume, buildCsvFromEntries } from 'services';
import { ResumeEntry } from './types';
import { EntryBuilder } from './components/EntryBuilder';

const DEFAULT_MODEL = 'gemini-2.5-flash';


export default function App() {
  const [entries, setEntries] = useState<ResumeEntry[]>([]);
  const [userId, setUserId] = useState<string>('user1');
  const [loading, setLoading] = useState(false);
  const [resumeJson, setResumeJson] = useState<any>(null);
  const [jobDescription, setJobDescription] = useState('');
  const [format, setFormat] = useState<'latex' | 'word'>('latex');
  const [error, setError] = useState<string | null>(null);

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
      const res = await generateResume(userId, {
        job_description: jobDescription,
        format,
        model: DEFAULT_MODEL
      });
      setResumeJson(res);
    } catch (e: any) {
      setError(e.message || 'Generation failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto p-4 font-sans">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Better Resume Builder</h1>
          <p className="text-sm text-neutral-400">Create your jobs.csv and generate AI-assisted resumes.</p>
        </div>
        <div className="flex gap-4 items-center">
          <label className="text-sm flex flex-col">User ID
            <input className="mt-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-sm focus:outline-none focus:ring focus:ring-indigo-500" value={userId} onChange={e => setUserId(e.target.value)} />
          </label>
          <label className="text-sm flex flex-col">Format
            <select className="mt-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-sm" value={format} onChange={e => setFormat(e.target.value as any)}>
              <option value='latex'>LaTeX</option>
              <option value='word'>Word</option>
            </select>
          </label>
        </div>
      </header>
  <EntryBuilder entries={entries} onAdd={addEntry} onUpdate={updateEntry} onRemove={removeEntry} />

      <section className="space-y-4 mb-12">
        <h2 className="text-xl font-semibold">Target Job Description</h2>
        <textarea className="w-full min-h-[200px] bg-neutral-900 border border-neutral-800 rounded p-3 text-sm resize-y focus:outline-none focus:ring focus:ring-indigo-500" value={jobDescription} onChange={e => setJobDescription(e.target.value)} placeholder='Paste job description here...' />
        <div className="flex flex-wrap gap-2">
          <button className="px-3 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-sm" disabled={!entries.some(e=>e.type!== 'info') || loading} onClick={handleUpload}>Upload jobs.csv</button>
          <button className="px-3 py-2 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-sm" disabled={loading || !jobDescription} onClick={handleGenerate}>Generate Resume</button>
        </div>
        {loading && <p className="text-sm text-neutral-400">Working...</p>}
        {error && <p className="text-sm text-red-400">{error}</p>}
      </section>
    </div>
  );
}

// Legacy interface (used by csv util older function). Safe to remove if unused.
export interface JobRecord { title: string; company: string; startDate: string; endDate: string; description: string; }
