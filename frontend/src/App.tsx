import React, { useState, useEffect, useCallback } from 'react';
// Use explicit relative path so Vite resolves without custom alias
import { uploadJobsCsv, generateResumeStream, buildCsvFromEntries } from './services';
import { ResumeEntry } from './types';
import { EntryBuilder } from './components/EntryBuilder';
import { OnboardingWizard } from './components/OnboardingWizard.js';
import { AuthGate, UserBar } from './components/AuthGate';
import { logout, loadUserData, saveUserDataIfExperienceChanged } from './services/firebase';
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
    return 'word';
  });
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<{stage:string; message?:string}[]>([]);
  const [downloading, setDownloading] = useState<null | 'pdf' | 'source'>(null);
  const [showGenModal, setShowGenModal] = useState(false);
  const [showJson, setShowJson] = useState(false);
  const [resumeCount, setResumeCount] = useState<number>(()=>{
    try { const v = localStorage.getItem('br.resumeCount'); return v? parseInt(v)||0 : 0; } catch { return 0; }
  });
  const [showDonate, setShowDonate] = useState(false);
  const pdfSectionRef = React.useRef<HTMLDivElement | null>(null);
  const [onboardingComplete, setOnboardingComplete] = useState<boolean>(() => {
    try { return localStorage.getItem('br.onboardingComplete') === '1'; } catch { return false; }
  });
  const ADS_CLIENT = import.meta.env.VITE_ADSENSE_CLIENT;
  const ADS_SLOT = import.meta.env.VITE_ADSENSE_SLOT_GENERATE;

  // Load AdSense script on demand when generation modal opens
  useEffect(()=>{
    if (!showGenModal || !ADS_CLIENT) return;
    if (!(window as any)._adsenseLoaded) {
      const s = document.createElement('script');
      s.async = true;
      s.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${encodeURIComponent(ADS_CLIENT)}`;
      s.crossOrigin = 'anonymous';
      s.onload = () => { (window as any)._adsenseLoaded = true; try { (window as any).adsbygoogle = (window as any).adsbygoogle || []; (window as any).adsbygoogle.push({}); } catch(_){} };
      document.head.appendChild(s);
    } else {
      try { (window as any).adsbygoogle = (window as any).adsbygoogle || []; (window as any).adsbygoogle.push({}); } catch(_){}
    }
  }, [showGenModal, ADS_CLIENT]);

  // Update meta description (and social tags) when language changes
  useEffect(()=>{
    const content = t('app.meta.description');
    function setTag(selector: string, attr: string = 'content') {
      let el = document.querySelector(selector) as HTMLMetaElement | null;
      if (!el) {
        if (selector.startsWith('meta[name="description"')) {
          el = document.createElement('meta');
          el.name = 'description';
          document.head.appendChild(el);
        } else if (selector.includes('property="og:description"')) {
          el = document.createElement('meta');
          el.setAttribute('property','og:description');
          document.head.appendChild(el);
        } else if (selector.includes('name="twitter:description"')) {
          el = document.createElement('meta');
          el.name = 'twitter:description';
          document.head.appendChild(el);
        }
      }
      if (el) el.setAttribute(attr, content);
    }
    setTag('meta[name="description" ]');
    setTag('meta[property="og:description"]');
    setTag('meta[name="twitter:description"]');
  }, [lang, t]);

  // Persist state to localStorage (debounced minimal by relying on React batch)
  useEffect(() => { try { localStorage.setItem('br.entries', JSON.stringify(entries)); } catch {} }, [entries]);
  // Hydrate from Firestore via AuthGate callback (legacy effect removed)

  // Removed continuous auto-save; persistence now triggered only on explicit upload.
  // no longer store userId directly; guests stored inside AuthGate logic
  useEffect(() => { try { localStorage.setItem('br.jobDescription', jobDescription); } catch {} }, [jobDescription]);
  useEffect(() => { try { localStorage.setItem('br.format', format); } catch {} }, [format]);
  useEffect(() => { try { localStorage.setItem('br.onboardingComplete', onboardingComplete? '1':'0'); } catch {} }, [onboardingComplete]);

  const addEntry = (entry: ResumeEntry) => setEntries(p => [...p, entry]);
  const updateEntry = (index: number, entry: ResumeEntry) => setEntries(p => p.map((e,i)=> i===index? entry : e));
  const removeEntry = (index: number) => setEntries(p => p.filter((_,i)=> i!==index));

  // Internal upload helper used by both explicit upload and generation. Does not manage loading state.
  const performUpload = async () => {
    const csv = buildCsvFromEntries(entries);
    const blob = new Blob([csv], { type: 'text/csv' });
    const file = new File([blob], 'jobs.csv', { type: 'text/csv' });
    await uploadJobsCsv(userId, file);
    if (user?.mode === 'auth') {
      // Persist only if experience entries changed
      saveUserDataIfExperienceChanged(user.uid, { entries, jobDescription, format }).catch(()=>{});
    }
  };

  const handleUpload = async () => {
    try {
      setError(null);
      setLoading(true);
      await performUpload();
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
  // Clear previous outputs so UI doesn't show outdated preview while regenerating
  setDownloadLinks(null);
  setResumeJson(null);
  setShowGenModal(true);
      // First upload latest entries as jobs.csv (silent: no alert)
      await performUpload();
      const res = await generateResumeStream(userId, {
        job_description: jobDescription,
        format,
        model: DEFAULT_MODEL
      }, evt => {
        setProgress(p => [...p, {stage: evt.stage, message: evt.message}]);
      });
      setResumeJson(res.result);
      if (res.files) setDownloadLinks(res.files);
      // Increment successful generation count
      setResumeCount(c => {
        const next = c + 1;
        try { localStorage.setItem('br.resumeCount', String(next)); } catch {}
        // Show donation modal exactly once when reaching 3 (unless previously dismissed)
  try { const prompted = localStorage.getItem('br.donatePrompted'); if (next >= 5 && !prompted) { setShowDonate(true); localStorage.setItem('br.donatePrompted','1'); } } catch {}
        return next;
      });
    } catch (e: any) {
      setError(e.message || 'Generation failed');
    } finally {
      setLoading(false);
  setTimeout(()=> setShowGenModal(false), 600); // slight delay for UX
    }
  };

  const handleDownload = async (kind: 'pdf' | 'source') => {
    if (!downloadLinks) return;
    const url = kind === 'pdf' ? downloadLinks.pdf : downloadLinks.source;
    try {
      setDownloading(kind);
      // Attempt fetch to ensure file exists and to avoid popup blockers / blocked navigation
      const res = await fetch(url, { method: 'GET' });
      if (!res.ok) {
        throw new Error(`File not ready (${res.status})`);
      }
      const blob = await res.blob();
      const fname = url.split('/').pop() || (kind === 'pdf' ? 'resume.pdf' : 'resume');
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = fname;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(()=> URL.revokeObjectURL(link.href), 5000);
    } catch (e:any) {
      setError(e.message || 'Download failed');
    } finally {
      setDownloading(null);
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

  // Determine if onboarding needed: require at least basic personal info (name, email, phone, address/website optional) then education/certification, then any experience.
  const hasPersonalBasics = entries.filter(e=>e.type==='info').map(e=>e.role).includes('name') && entries.filter(e=>e.type==='info').map(e=>e.role).includes('email');
  // We allow finishing onboarding even without phone but you can adjust.
  const hasEducationOrCert = entries.some(e=> e.type==='education' || e.type==='certification');
  const wizardNeeded = !onboardingComplete || !hasPersonalBasics || !hasEducationOrCert;

  // Compute progress percent from stages
  const stageOrder = ['invoking_graph','graph_complete','parsed','translating','translated','writing_file','done'];
  const latestStage = progress.length ? progress[progress.length-1].stage : null;
  const percent = latestStage ? Math.min(100, Math.round(((stageOrder.indexOf(latestStage) + 1) / stageOrder.length) * 100)) : (showGenModal ? 5 : 0);

  useEffect(()=>{
    if (downloadLinks?.pdf && pdfSectionRef.current) {
      // Scroll PDF section into view after generation completes
      pdfSectionRef.current.scrollIntoView({behavior:'smooth'});
    }
  }, [downloadLinks?.pdf]);

  return (
    <div className="max-w-5xl mx-auto p-4 font-sans relative">
      <header className="mb-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <img src="/logo2.png" alt={t('app.title')} className="h-16 sm:h-20 w-auto select-none" draggable={false} />
            <div className="flex flex-col justify-center">
              <p className="sr-only">{t('app.title')}</p>
              <p className="text-sm text-neutral-400 leading-snug max-w-xs">{t('app.tagline')}</p>
            </div>
          </div>
          <div className="flex gap-4 items-center flex-wrap justify-end">
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
        <option value='latex'>{t('format.latex')}</option>
        <option value='word'>{t('format.word')}</option>
            </select>
          </label>
      <label className="text-sm flex flex-col">{t('app.language')}
            <select className="mt-1 bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-sm" value={lang} onChange={e => setLang(e.target.value as any)}>
              {availableLanguages.map(l => <option key={l.code} value={l.code}>{t(l.labelKey)}</option>)}
            </select>
          </label>
          </div>
        </div>
      </header>
  {wizardNeeded ? (
    <OnboardingWizard
      entries={entries}
      addEntry={addEntry}
      updateEntry={updateEntry}
      removeEntry={removeEntry}
      onFinish={() => setOnboardingComplete(true)}
    />
  ) : (
    <EntryBuilder entries={entries} onAdd={addEntry} onUpdate={updateEntry} onRemove={removeEntry} />
  )}

      <section className="space-y-4 mb-12">
        <h2 className="text-xl font-semibold">{t('job.description.section')}</h2>
  <textarea className="w-full min-h-[200px] bg-neutral-900 border border-neutral-800 rounded p-3 text-sm resize-y focus:outline-none focus:ring focus:ring-red-500" value={jobDescription} onChange={e => setJobDescription(e.target.value)} placeholder={t('job.description.placeholder')} />
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary btn-sm" disabled={loading || !jobDescription} onClick={handleGenerate}>{t('generate.resume')}</button>
          <button type="button" className="btn-secondary btn-sm" onClick={clearAll}>{t('button.clear')}</button>
        </div>
        {loading && <p className="text-sm text-neutral-400">{t('working')}</p>}
        {progress.length>0 && (
          <ul className="text-xs text-neutral-400 space-y-1 bg-neutral-900 border border-neutral-800 rounded p-2 max-h-48 overflow-auto">
            {progress.map((p,i)=>(<li key={i}><span className="font-mono text-neutral-500">{i+1}.</span> {p.stage}{p.message?`: ${p.message}`:''}</li>))}
          </ul>
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}
        {resumeJson && (
          <div className="mt-6 space-y-2 bg-neutral-900/40 rounded">
            <button type="button" onClick={()=>setShowJson(s=>!s)} className="btn-link-primary text-xs px-3 py-2">
              {showJson ? t('json.hide') : t('json.show')}
            </button>
            {showJson && (
              <div className="space-y-3 border-t border-neutral-800 pt-3 px-4 pb-4">
                <h3 className="text-sm font-semibold">{t('json.title')}</h3>
                <pre className="text-xs overflow-auto max-h-96 bg-neutral-950 p-3 rounded border border-neutral-800">{JSON.stringify(resumeJson, null, 2)}</pre>
              </div>
            )}
          </div>
        )}
    </section>
    {downloadLinks?.pdf && (
      <section ref={pdfSectionRef} className="mb-24 space-y-4">
        <h2 className="text-xl font-semibold">{t('preview.title')}</h2>
        <div className="w-full border border-neutral-800 rounded bg-neutral-900 aspect-[8.5/11] relative overflow-hidden">
          <iframe title="Resume PDF" src={downloadLinks.pdf} className="w-full h-full" />
          {!downloadLinks.pdf && <div className="absolute inset-0 flex items-center justify-center text-sm text-neutral-500">{t('preview.pdf.unavailable')}</div>}
        </div>
        <div className="flex gap-4 flex-wrap">
          <button disabled={downloading==='pdf'} onClick={()=>handleDownload('pdf')} className="btn-primary disabled:opacity-50">{downloading==='pdf' ? t('download.downloading') : t('download.pdf')}</button>
          <button disabled={downloading==='source'} onClick={()=>handleDownload('source')} className="btn-secondary disabled:opacity-50">{downloading==='source' ? t('download.preparing') : t('download.source')}</button>
        </div>
      </section>
    )}
    {showGenModal && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
        <div className="w-full max-w-md bg-neutral-900 border border-neutral-700 rounded-lg p-6 shadow-xl space-y-6">
          <div className="flex items-center gap-3">
            <div className="relative w-10 h-10">
              <div className="absolute inset-0 rounded-md bg-red-600 animate-pulse" />
              <div className="absolute inset-1 rounded-sm bg-neutral-900 flex items-center justify-center text-[10px] font-semibold tracking-wide">CV</div>
            </div>
            <div>
              <h3 className="font-semibold">{t('modal.building.title')}</h3>
              <p className="text-xs text-neutral-400">{t('modal.building.subtitle')}</p>
            </div>
          </div>
          <div>
            <div className="h-2 w-full rounded bg-neutral-800 overflow-hidden">
              <div className="h-full bg-gradient-to-r from-red-500 via-rose-500 to-red-500 animate-[progressMove_2s_linear_infinite]" style={{width: percent+"%"}} />
            </div>
            <div className="flex justify-between mt-1 text-[11px] text-neutral-500"><span>{percent}%</span><span>{latestStage || t('progress.starting')}</span></div>
          </div>
          <div className="flex gap-2 flex-wrap text-[10px] text-neutral-400 max-h-24 overflow-auto">
            {progress.slice(-4).map((p,i)=>(<span key={i} className="px-2 py-1 bg-neutral-800 rounded">{p.stage}</span>))}
          </div>
          {ADS_CLIENT && ADS_SLOT && (
            <div className="mt-2">
              <div className="text-[10px] uppercase tracking-wide text-neutral-600 mb-1">Ad</div>
              <ins className="adsbygoogle block" style={{display:'block'}} data-ad-client={ADS_CLIENT} data-ad-slot={ADS_SLOT} data-ad-format="auto" data-full-width-responsive="true"></ins>
            </div>
          )}
        </div>
      </div>
    )}
    {showDonate && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
        <div className="w-full max-w-md bg-neutral-900 border border-red-700/50 rounded-xl p-6 shadow-2xl space-y-5 relative">
          <button onClick={()=>setShowDonate(false)} className="absolute top-2 right-2 text-neutral-500 hover:text-neutral-300 text-xs">✕</button>
          <h3 className="text-xl font-semibold tracking-tight">{t('donate.title')}</h3>
          <p className="text-sm text-neutral-400 leading-relaxed">{t('donate.body')}</p>
          <div className="flex gap-3 flex-wrap">
            <a href="https://buymeacoffee.com/" target="_blank" rel="noreferrer" className="btn-primary">{t('donate.cta')}</a>
            <button onClick={()=>setShowDonate(false)} className="btn-secondary">{t('donate.later')}</button>
          </div>
          <p className="text-[11px] text-neutral-500">{t('donate.footer')}</p>
        </div>
      </div>
    )}
  <AuthGate forceOpenSignal={authGateOpenSignal} onResolved={useCallback((u, data) => {
      setUser(u);
      if (data) {
        if (Array.isArray(data.entries)) {
          setEntries(data.entries as any);
          // Evaluate onboarding completion based on loaded entries (skip wizard if already satisfied)
          try {
            const loaded = data.entries as ResumeEntry[];
            const roles = loaded.filter(e=>e.type==='info').map(e=>e.role);
            const hasPersonal = roles.includes('name') && roles.includes('email');
            if (hasPersonal) {
              setOnboardingComplete(true);
            }
          } catch {}
        }
        if (data.jobDescription) setJobDescription(data.jobDescription);
        if (data.format === 'latex' || data.format === 'word') setFormat(data.format);
      }
    }, [])} />
  </div>
  );
}

// Legacy interface (used by csv util older function). Safe to remove if unused.
export interface JobRecord { title: string; company: string; startDate: string; endDate: string; description: string; }

// Tailwind arbitrary animation keyframes (progressMove) can be defined via inline @layer if needed globally
