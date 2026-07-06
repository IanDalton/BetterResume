import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadJobsJson, generateResumeStream, buildJobsFromEntries, resolveProfilePictureUrl, getProfile, saveProfile, getLanguages, saveLanguages } from '../services';
import { EXPERIENCE_TYPES, LanguageEntry, ResumeEntry, UserProfile, emptyProfile } from '../types';
import { ProfileEditor } from '../components/entries';
import { SaveStatus } from '../components/entries/SaveStatusIndicator';
import { Footer } from '../components/Footer';
import { AuthGate, UserBar } from '../components/AuthGate';
import { FirstLoadGuide } from '../components/FirstLoadGuide';
import { DonateToast } from '../components/DonateToast';
import { AdBanner } from '../components/AdBanner';
import { ProfilePictureUploader } from '../components/ProfilePictureUploader';
import { logout, loadUserData, saveUserDataIfChanged } from '../services/firebase';
import { splitLegacyEntries, hasLegacyEntries } from '../services/legacyMigration';
import { useI18n, availableLanguages } from '../i18n';
import { initAnalytics, pageView, setupErrorTracking, trackConsole, trackEvent } from '../services/analytics';
import { detectCountry } from '../services/geolocation';
import { Dialog, Button } from '../components/ui';
import { useToast } from '../components/ui/use-toast';
import { ThemeToggle } from '../components/ThemeToggle';

// Loads and, if needed, one-time-splits legacy localStorage data (mixed
// personal-info/language rows inside br.entries) into the new dedicated
// br.profile/br.languages/br.entries keys. Cached at module scope so the
// three useState lazy initializers below don't each redo the same parse.
let _initialLocalData: { profile: UserProfile; languages: LanguageEntry[]; entries: ResumeEntry[] } | null = null;
function loadInitialLocalData() {
  if (_initialLocalData) return _initialLocalData;
  let profile: UserProfile = { ...emptyProfile };
  let languages: LanguageEntry[] = [];
  let entries: ResumeEntry[] = [];
  try {
    const rawEntries = JSON.parse(localStorage.getItem('br.entries') || '[]');
    if (hasLegacyEntries(rawEntries)) {
      const split = splitLegacyEntries(rawEntries);
      profile = { ...emptyProfile, ...split.profile };
      languages = split.languages;
      entries = split.entries;
      try {
        localStorage.setItem('br.profile', JSON.stringify(profile));
        localStorage.setItem('br.languages', JSON.stringify(languages));
        localStorage.setItem('br.entries', JSON.stringify(entries));
      } catch {}
    } else {
      entries = Array.isArray(rawEntries) ? rawEntries : [];
      try { const p = localStorage.getItem('br.profile'); if (p) profile = { ...emptyProfile, ...JSON.parse(p) }; } catch {}
      try { const l = localStorage.getItem('br.languages'); if (l) languages = JSON.parse(l); } catch {}
    }
  } catch {}
  _initialLocalData = { profile, languages, entries };
  return _initialLocalData;
}

export function Home() {
  const { t, lang, setLang } = useI18n();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [profile, setProfile] = useState<UserProfile>(() => loadInitialLocalData().profile);
  const [languages, setLanguages] = useState<LanguageEntry[]>(() => loadInitialLocalData().languages);
  const [entries, setEntries] = useState<ResumeEntry[]>(() => loadInitialLocalData().entries);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [user, setUser] = useState<{mode:'auth'|'guest'; uid:string; email?:string} | null>(null);
  const [authGateOpenSignal, setAuthGateOpenSignal] = useState(0);
  // Always generate a fresh guest UUID on each reload to avoid cross-session mixing
  const [guestId] = useState(()=>{
    try {
      const gen: string = (typeof crypto !== 'undefined' && (crypto as any).randomUUID)
        ? (crypto as any).randomUUID()
        : 'guest-' + Date.now().toString(36);
      try { localStorage.setItem('br.guestId', gen); } catch {}
      return gen;
    } catch (error) {
      console.error('Error generating guest ID:', error);
      return 'guest-' + Date.now().toString(36);
    }
  });
  const userId = user?.uid || guestId;
  const [loading, setLoading] = useState(false);
  const [resumeJson, setResumeJson] = useState<any>(null);
  const [downloadLinks, setDownloadLinks] = useState<{pdf:string; source:string}|null>(null);
  const [profilePictureUrl, setProfilePictureUrl] = useState<string | null>(null);
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
  const [genStartAt, setGenStartAt] = useState<number | null>(null);
  const [firstEventAt, setFirstEventAt] = useState<number | null>(null);
  const [resumeCount, setResumeCount] = useState<number>(()=>{
    try { const v = localStorage.getItem('br.resumeCount'); return v? parseInt(v)||0 : 0; } catch { return 0; }
  });
  const [showDonate, setShowDonate] = useState(false);
  const [showGuide, setShowGuide] = useState<boolean>(() => {
    try { return localStorage.getItem('br.guideSeen') !== '1'; } catch { return true; }
  });
  const [showDonateToast, setShowDonateToast] = useState(false);
  const [geoLocation, setGeoLocation] = useState<{isOutsideUS: boolean; isArgentina: boolean; country: string} | null>(null);
  const pdfSectionRef = React.useRef<HTMLDivElement | null>(null);
  const [onboardingComplete, setOnboardingComplete] = useState<boolean>(() => {
    try { return localStorage.getItem('br.onboardingComplete') === '1'; } catch { return false; }
  });
  const [includeProfilePicture, setIncludeProfilePicture] = useState<boolean>(() => {
    try { return localStorage.getItem('br.includeProfilePicture') === '1'; } catch { return false; }
  });
  const handleProfileUploaded = useCallback((url: string | null) => {
    setProfilePictureUrl(url);
    if (!url && includeProfilePicture) {
      setIncludeProfilePicture(false);
    }
  }, [includeProfilePicture]);
  const ADS_CLIENT = import.meta.env.VITE_ADSENSE_CLIENT;
  const ADS_SLOT = import.meta.env.VITE_ADSENSE_SLOT_GENERATE;
  const GA_MEASUREMENT_ID = import.meta.env.VITE_GA_MEASUREMENT_ID as string | undefined;

  useEffect(()=>{
    if (GA_MEASUREMENT_ID) {
      initAnalytics(GA_MEASUREMENT_ID);
      setupErrorTracking();
      trackConsole();
      pageView(window.location.pathname, document.title);
    }
  }, [GA_MEASUREMENT_ID]);

  // Detect user geolocation on mount
  useEffect(() => {
    let cancelled = false;
    detectCountry().then((geo) => {
      if (!cancelled) {
        setGeoLocation({
          isOutsideUS: geo.isOutsideUS,
          isArgentina: geo.isArgentina,
          country: geo.country,
        });
      }
    }).catch((error) => {
      console.error('Failed to detect geolocation:', error);
      // Default to US if detection fails
      if (!cancelled) {
        setGeoLocation({
          isOutsideUS: false,
          isArgentina: false,
          country: t('geo.unknown'),
        });
      }
    });
    return () => { cancelled = true; };
  }, [t]);

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
  useEffect(() => { try { localStorage.setItem('br.profile', JSON.stringify(profile)); } catch {} }, [profile]);
  useEffect(() => { try { localStorage.setItem('br.languages', JSON.stringify(languages)); } catch {} }, [languages]);
  // Hydrate from Firestore via AuthGate callback (legacy effect removed)

  // Background autosave: profile/languages are cheap upserts (no pgvector
  // re-ingest), so sync them to the backend shortly after any edit instead of
  // only on explicit Upload/Generate -- closes the "navigate away mid-edit"
  // data-loss gap. Work-experience entries still sync only via performUpload
  // (that pipeline re-ingests pgvector documents and is too expensive to run
  // on every keystroke).
  const autosaveTimer = useRef<number | null>(null);
  const skipFirstAutosave = useRef(true);
  useEffect(() => {
    if (skipFirstAutosave.current) { skipFirstAutosave.current = false; return; }
    if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    setSaveStatus('saving');
    autosaveTimer.current = window.setTimeout(async () => {
      try {
        await Promise.all([saveProfile(userId, profile), saveLanguages(userId, languages)]);
        if (user?.mode === 'auth') {
          saveUserDataIfChanged(user.uid, { entries, profile, languages, jobDescription, format }).catch(() => {});
        }
        setSaveStatus('saved');
        window.setTimeout(() => setSaveStatus((s) => (s === 'saved' ? 'idle' : s)), 2000);
      } catch {
        setSaveStatus('error');
      }
    }, 1200);
    return () => { if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, languages, userId]);

  // Removed continuous auto-save; persistence now triggered only on explicit upload.
  // no longer store userId directly; guests stored inside AuthGate logic
  useEffect(() => { try { localStorage.setItem('br.jobDescription', jobDescription); } catch {} }, [jobDescription]);
  useEffect(() => { try { localStorage.setItem('br.format', format); } catch {} }, [format]);
  useEffect(() => { try { localStorage.setItem('br.onboardingComplete', onboardingComplete? '1':'0'); } catch {} }, [onboardingComplete]);
  useEffect(() => { if (!showGuide) { try { localStorage.setItem('br.guideSeen','1'); } catch {} } }, [showGuide]);
  useEffect(() => { try { localStorage.setItem('br.includeProfilePicture', includeProfilePicture && !!profilePictureUrl ? '1' : '0'); } catch {} }, [includeProfilePicture, profilePictureUrl]);

  useEffect(() => {
    let cancelled = false;
    async function loadProfilePicture() {
      const url = await resolveProfilePictureUrl(userId);
      if (cancelled) return;
      setProfilePictureUrl(url);
    }
    loadProfilePicture();
    return () => { cancelled = true; };
  }, [userId]);

  useEffect(() => {
    if (!profilePictureUrl && includeProfilePicture) {
      setIncludeProfilePicture(false);
    }
  }, [profilePictureUrl, includeProfilePicture]);
  // Utility: show toast now and record timestamps/counters
  const triggerDonateToast = useCallback((reason: 'daily' | 'count') => {
    try {
      if (reason === 'count') localStorage.setItem('br.toastDonateGenCount', '0');
      localStorage.setItem('br.toastDonateLastShown', String(Date.now()));
    } catch {}
    setShowDonateToast(true);
  }, []);

  useEffect(() => {
    // Passive daily reminder: show at most once per day
    const lastShown = Number.parseInt(localStorage.getItem('br.toastDonateLastShown') || '0');
    const dayElapsed = (Date.now() - lastShown) > 86_400_000; // 24h
    if (dayElapsed) {
      const id = setTimeout(() => {
        if (!showGenModal && !showGuide) triggerDonateToast('daily');
      }, 1500);
      return () => clearTimeout(id);
    }
  }, [showGenModal, showGuide, triggerDonateToast]);

  // Stripe donation toast: show to non-US users after 3 resumes or daily
  useEffect(() => {
    if (!geoLocation || !geoLocation.isOutsideUS || geoLocation.isArgentina) return;
    
    const lastShown = Number.parseInt(localStorage.getItem('br.stripeDonateShown') || '0');
    const dayElapsed = (Date.now() - lastShown) > 86_400_000; // 24h
    
    // Show if 3+ resumes generated or daily reminder
    if ((resumeCount >= 3 && dayElapsed) || (resumeCount >= 5)) {
      const id = setTimeout(() => {
        if (!showGenModal && !showGuide && !showDonateToast) {
          // Instead of showing toast, maybe just show the donate modal or navigate?
          // For now, let's just show the donate toast which leads to /donate
          setShowDonateToast(true);
        }
      }, 2000);
      return () => clearTimeout(id);
    }
  }, [resumeCount, geoLocation, showGenModal, showGuide, showDonateToast]);

  const addEntry = (entry: ResumeEntry) => setEntries(p => [...p, entry]);
  const updateEntry = (index: number, entry: ResumeEntry) => setEntries(p => p.map((e,i)=> i===index? entry : e));
  const removeEntry = (index: number) => setEntries(p => p.filter((_,i)=> i!==index));

  // Internal upload helper used by both explicit upload and generation. Does not manage loading state.
  const [uploading, setUploading] = useState(false);
  const performUpload = async () => {
    if (uploading) return; // guard
    setUploading(true);
    try {
      const jobs = buildJobsFromEntries(entries);
      // Profile/languages must be flushed synchronously here (not left to the
      // debounced autosave) so generation always reads fresh personal info.
      const [result] = await Promise.all([
        uploadJobsJson(userId, jobs),
        saveProfile(userId, profile),
        saveLanguages(userId, languages),
      ]);
      if (user?.mode === 'auth') {
        // Persist only if experience/profile/languages actually changed
        saveUserDataIfChanged(user.uid, { entries, profile, languages, jobDescription, format }).catch(()=>{});
      }
      return result;
    } finally {
      setUploading(false);
    }
  };

  const handleUpload = async () => {
    try {
      setError(null);
      setLoading(true);
      const res: any = await performUpload();
      if (res?.status === 'unchanged') {
        toast({ title: t('upload.unchanged') });
      } else if (res?.rows_ingested != null) {
        toast({ title: `${t('upload.success.rows')} (${res.rows_ingested})`, variant: 'success' });
      } else {
        toast({ title: t('upload.success'), variant: 'success' });
      }
    } catch (e: any) {
      const message = e.message || t('upload.failed');
      setError(message);
      toast({ title: message, variant: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    try {
      setError(null);
      // Frontend guard: block calls if requirements not met
      if (!hasPersonalBasics) { setError(t('generate.error.personal')); return; }
      if (!hasExperience) { setError(t('generate.error.experience')); return; }
      setLoading(true);
      setGenStartAt(Date.now());
      setFirstEventAt(null);
      try { trackEvent('resume_generate_start', { format, entries: entries.length, has_job: !!jobDescription, auth: user?.mode==='auth' }); } catch {}
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
        include_profile_picture: includeProfilePicture && !!profilePictureUrl
      }, evt => {
        if (!firstEventAt) {
          setFirstEventAt(Date.now());
          if (genStartAt) {
            try { trackEvent('resume_stream_first_event', { ms: Date.now() - genStartAt, stage: evt.stage }); } catch {}
          }
        }
        const msg = evt.stage === 'csv_info' && (evt.rows != null) ? `rows: ${evt.rows}` : evt.message;
        setProgress(p => [...p, {stage: evt.stage, message: msg}]);
        if (evt.stage === 'error') {
          try { trackEvent('resume_generate_error', { message: evt.message||'error' }); } catch {}
        }
      });
      setResumeJson(res.result);
      if (res.files) setDownloadLinks(res.files);
      try {
        const dur = genStartAt ? (Date.now() - genStartAt) : undefined;
        const first = genStartAt && firstEventAt ? (firstEventAt - genStartAt) : undefined;
        trackEvent('resume_generate_success', { format, duration_ms: dur, first_event_ms: first });
      } catch {}
      // Increment successful generation count
      setResumeCount(c => {
        const next = c + 1;
        try { localStorage.setItem('br.resumeCount', String(next)); } catch {}
        // Donation toast cadence: every 5 generations
        try {
          const cur = Number.parseInt(localStorage.getItem('br.toastDonateGenCount') || '0');
          const updated = cur + 1;
          localStorage.setItem('br.toastDonateGenCount', String(updated));
          if (updated >= 5) {
            const lastShown = Number.parseInt(localStorage.getItem('br.toastDonateLastShown') || '0');
            const dayElapsed = (Date.now() - lastShown) > 86_400_000;
            if (!showGenModal && dayElapsed) {
              // Show and reset the counter
              setTimeout(() => triggerDonateToast('count'), 400);
            } else if (!showGenModal && lastShown === 0) {
              setTimeout(() => triggerDonateToast('count'), 400);
            }
          }
        } catch {}
        // Show donation modal exactly once when reaching 3 (unless previously dismissed)
  try { const prompted = localStorage.getItem('br.donatePrompted'); if (next >= 5 && !prompted) { setShowDonate(true); localStorage.setItem('br.donatePrompted','1'); } } catch {}
        return next;
      });
    } catch (e: any) {
      setError(e.message || t('generate.error.failed'));
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
        throw new Error(`${t('download.error.notReady')} (${res.status})`);
      }
      const blob = await res.blob();
      // Prefer filename from Content-Disposition when available
      let fname = '';
      const cd = res.headers ? (res.headers.get('Content-Disposition') || res.headers.get('content-disposition')) : null;
      if (cd && typeof cd === 'string') {
        // naive parse: filename="resume.pdf" or filename=resume.pdf
        const m = cd.match(/filename\*=UTF-8''([^;]+)|filename\s*=\s*"?([^";]+)"?/i);
        const raw = (m && (m[1] || m[2])) || '';
        try { fname = decodeURIComponent(raw); } catch { fname = raw; }
      }
      if (!fname) {
        try {
          const u = new URL(url);
          const parts = u.pathname.split('/');
          fname = parts[parts.length - 1] || (kind === 'pdf' ? 'resume.pdf' : 'resume');
        } catch {
          // Fallback: strip query if present
          const last = url.split('/').pop() || '';
          fname = last.split('?')[0] || (kind === 'pdf' ? 'resume.pdf' : 'resume');
        }
      }
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = fname;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(()=> URL.revokeObjectURL(link.href), 5000);
    } catch (e:any) {
      setError(e.message || t('download.error.failed'));
    } finally {
      setDownloading(null);
    }
  };

  const clearAll = () => {
    if (!confirm(t('confirm.clear'))) return;
    try {
      localStorage.removeItem('br.entries');
      localStorage.removeItem('br.profile');
      localStorage.removeItem('br.languages');
    localStorage.removeItem('br.guestId');
      localStorage.removeItem('br.jobDescription');
      localStorage.removeItem('br.format');
    } catch {}
    setEntries([]);
    setProfile({ ...emptyProfile });
    setLanguages([]);
  setUser(null);
    setJobDescription('');
    setFormat('latex');
    setResumeJson(null);
    setError(null);
  };

  // Require basic personal info (name + email) and at least one experience entry.
  const hasPersonalBasics = !!(profile.fullName && profile.email);
  const hasExperience = entries.some(e => EXPERIENCE_TYPES.includes(e.type));

  // Compute progress percent from stages
  const stageOrder = ['csv_info','invoking_graph','graph_complete','parsed','translating','translated','writing_file','done'];
  const latestStage = progress.length ? progress[progress.length-1].stage : null;
  const idx = latestStage ? stageOrder.indexOf(latestStage) : -1;
  const percent = idx >= 0 ? Math.min(100, Math.round(((idx + 1) / stageOrder.length) * 100)) : (showGenModal ? 5 : 0);

  const [pdfUrl, setPdfUrl] = useState<string|null>(null);

  useEffect(()=>{
    if (downloadLinks?.pdf && pdfSectionRef.current) {
      // Scroll PDF section into view after generation completes
      pdfSectionRef.current.scrollIntoView({behavior:'smooth'});
    }
    
    // Fetch PDF as blob to bypass CSP frame-ancestors restrictions
    let active = true;
    if (downloadLinks?.pdf) {
      if (downloadLinks.pdf.startsWith('blob:') || downloadLinks.pdf.startsWith('data:')) {
        setPdfUrl(downloadLinks.pdf);
      } else {
        fetch(downloadLinks.pdf)
          .then(res => res.blob())
          .then(blob => {
            if (active) {
              const url = URL.createObjectURL(blob);
              setPdfUrl(url);
            }
          })
          .catch(err => {
            console.error('Failed to fetch PDF blob:', err);
            if (active) setPdfUrl(downloadLinks.pdf);
          });
      }
    } else {
      setPdfUrl(null);
    }
    return () => {
      active = false; 
      // Note: we strictly should revokeObjectURL here if we created one, 
      // but simplistic handling suffices for this single-page view.
    };
  }, [downloadLinks?.pdf]);

  return (
  <div className="max-w-5xl mx-auto p-4 pb-16 font-sans relative">
      <header className="mb-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <img src="/logo2.png" alt={t('app.title')} className="h-16 sm:h-20 w-auto select-none" draggable={false} />
            <div className="flex flex-col justify-center">
              <p className="sr-only">{t('app.title')}</p>
              <p className="text-sm text-neutral-600 dark:text-neutral-400 leading-snug max-w-xs">{t('app.tagline')}</p>
            </div>
          </div>
          <div className="flex gap-3 items-center flex-wrap justify-end">
          <button type="button" title={t('guide.button.title')} onClick={()=>setShowGuide(true)} className="btn-secondary btn-sm px-2 py-1">
            <span aria-hidden>❓</span>
          </button>
          {user && <UserBar user={user} onLogout={async ()=>{
  await logout();
  setUser(null);
  setEntries([]);
  setProfile({ ...emptyProfile });
  setLanguages([]);
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
            <select className="mt-1 bg-white dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded px-2 py-1 text-sm" value={format} onChange={e => setFormat(e.target.value as any)}>
        <option value='latex'>{t('format.latex')}</option>
        <option value='word'>{t('format.word')}</option>
            </select>
          </label>
          <label className="text-sm flex flex-col">{t('app.language')}
            <select className="mt-1 bg-white dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded px-2 py-1 text-sm" value={lang} onChange={e => setLang(e.target.value as any)}>
              {availableLanguages.map(l => <option key={l.code} value={l.code}>{t(l.labelKey)}</option>)}
            </select>
          </label>
          <ThemeToggle />
          </div>
        </div>
      </header>
  <ProfileEditor
    userId={userId}
    profile={profile}
    onProfileChange={setProfile}
    languages={languages}
    onLanguagesChange={setLanguages}
    entries={entries}
    onAddEntry={addEntry}
    onUpdateEntry={updateEntry}
    onRemoveEntry={removeEntry}
    onboardingComplete={onboardingComplete}
    onOnboardingComplete={() => setOnboardingComplete(true)}
    saveStatus={saveStatus}
  />

  <ProfilePictureUploader
    userId={userId}
    include={includeProfilePicture}
    onIncludeChange={setIncludeProfilePicture}
    imageUrl={profilePictureUrl}
    onUploaded={handleProfileUploaded}
  />

  <section className="space-y-4 mb-12">
        <h2 className="text-xl font-semibold">{t('job.description.section')}</h2>
  <textarea className="w-full min-h-[200px] bg-white dark:bg-neutral-900 border border-neutral-300 dark:border-neutral-800 rounded p-3 text-sm resize-y focus:outline-none focus:ring focus:ring-red-500" value={jobDescription} onChange={e => setJobDescription(e.target.value)} placeholder={t('job.description.placeholder')} />
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary btn-sm" disabled={loading || !jobDescription || !hasPersonalBasics || !hasExperience} onClick={handleGenerate}>{t('generate.resume')}</button>
          <button type="button" className="btn-secondary btn-sm" onClick={()=>{ trackEvent('clear_click'); clearAll(); }}>{t('button.clear')}</button>
        </div>
        {(!hasPersonalBasics || !hasExperience) && (
          <p className="text-xs text-red-500">
            {!hasPersonalBasics ? t('validation.personal') : t('validation.experience')}
          </p>
        )}
  {loading && <p className="text-sm text-neutral-600 dark:text-neutral-400">{t('working')}</p>}
        {progress.length>0 && (
          <ul className="text-xs text-neutral-600 dark:text-neutral-400 space-y-1 bg-neutral-50 dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-800 rounded p-2 max-h-48 overflow-auto">
            {progress.map((p,i)=>(<li key={i}><span className="font-mono text-neutral-500">{i+1}.</span> {p.stage}{p.message?`: ${p.message}`:''}</li>))}
          </ul>
        )}
        {error && <p className="text-sm text-red-400">{error}</p>}
        {resumeJson && (
          <div className="mt-6 space-y-2 bg-neutral-50/80 dark:bg-neutral-900/40 rounded">
            <button type="button" onClick={()=>setShowJson(s=>!s)} className="btn-link-primary text-xs px-3 py-2">
              {showJson ? t('json.hide') : t('json.show')}
            </button>
            {showJson && (
              <div className="space-y-3 border-t border-neutral-800 pt-3 px-4 pb-4">
                <h3 className="text-sm font-semibold">{t('json.title')}</h3>
                <pre className="text-xs overflow-auto max-h-96 bg-neutral-100 dark:bg-neutral-950 p-3 rounded border border-neutral-200 dark:border-neutral-800">{JSON.stringify(resumeJson, null, 2)}</pre>
              </div>
            )}
          </div>
        )}
    </section>
    {downloadLinks && (
      <section ref={pdfSectionRef} className="mb-24 space-y-4">
        <h2 className="text-xl font-semibold">{t('preview.title')}</h2>
  <div className="w-full border border-neutral-200 dark:border-neutral-800 rounded bg-white dark:bg-neutral-900 aspect-[8.5/11] relative overflow-hidden">
          {pdfUrl ? (
            <iframe title="Resume PDF" src={pdfUrl} className="w-full h-full" />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-neutral-500">{t('preview.pdf.unavailable')}</div>
          )}
        </div>
        <div className="flex gap-4 flex-wrap">
          {downloadLinks.pdf && (
            <button disabled={downloading==='pdf'} onClick={()=>handleDownload('pdf')} className="btn-primary disabled:opacity-50">{downloading==='pdf' ? t('download.downloading') : t('download.pdf')}</button>
          )}
          {downloadLinks.source && (
            <button disabled={downloading==='source'} onClick={()=>handleDownload('source')} className="btn-secondary disabled:opacity-50">{downloading==='source' ? t('download.preparing') : t('download.source')}</button>
          )}
        </div>
      </section>
    )}
    <Dialog
      open={showGenModal}
      onOpenChange={() => {}}
      hideClose
      title={
        <span className="flex items-center gap-3">
          <span className="relative w-10 h-10 shrink-0">
            <span className="absolute inset-0 rounded-md bg-red-600 animate-pulse" />
            <span className="absolute inset-1 rounded-sm bg-white dark:bg-neutral-900 flex items-center justify-center text-[10px] font-semibold tracking-wide">CV</span>
          </span>
          {t('modal.building.title')}
        </span>
      }
      description={t('modal.building.subtitle')}
    >
      <div className="space-y-6">
        <div>
          <div className="h-2 w-full rounded bg-neutral-200 dark:bg-neutral-800 overflow-hidden">
            <div
              className="h-full bg-[length:200%_100%] bg-gradient-to-r from-red-500 via-rose-500 to-red-500 animate-progressMove"
              style={{ width: percent + '%' }}
            />
          </div>
          <div className="flex justify-between mt-1 text-[11px] text-neutral-600 dark:text-neutral-500"><span>{percent}%</span><span>{latestStage || t('progress.starting')}</span></div>
        </div>
        <div className="flex gap-2 flex-wrap text-[10px] text-neutral-500 dark:text-neutral-400 max-h-24 overflow-auto">
          {progress.slice(-4).map((p,i)=>(<span key={i} className="px-2 py-1 bg-neutral-100 dark:bg-neutral-800 rounded">{p.stage}</span>))}
        </div>
        {geoLocation?.isArgentina && (
        <div className="mt-2">
          <div className="text-[10px] uppercase tracking-wide text-neutral-600 mb-1">Ad</div>
          <a href="https://lannis.app?utm_source=web&utm_medium=banner&utm_campaign=august12&utm_id=better-resume" target="_blank" rel="noreferrer" className="block">
            <img src="/Lannis Ads-25.png" alt="Lannis" className="w-full h-auto" />
          </a>
        </div>
        )}
      </div>
    </Dialog>
  <FirstLoadGuide open={showGuide} onClose={()=>setShowGuide(false)} />
  <DonateToast 
    open={showDonateToast} 
    onClose={()=>{ try { localStorage.setItem('br.toastDonateLastShown', String(Date.now())); localStorage.setItem('br.toastDonateGenCount','0'); } catch {} setShowDonateToast(false); }} 
    onDonateClick={!geoLocation || !geoLocation.isArgentina ? () => { navigate('/donate'); setShowDonateToast(false); } : undefined}
  />
    <Dialog
      open={showDonate}
      onOpenChange={setShowDonate}
      title={t('donate.title')}
      description={t('donate.body')}
      footer={
        <>
          {!geoLocation || !geoLocation.isArgentina ? (
            <Button variant="primary" onClick={() => { navigate('/donate'); setShowDonate(false); }}>{t('donate.cta')}</Button>
          ) : (
            <Button asChild variant="primary">
              <a href="https://link.mercadopago.com.ar/betterresume" target="_blank" rel="noreferrer">{t('donate.cta')}</a>
            </Button>
          )}
          <Button variant="secondary" onClick={()=>setShowDonate(false)}>{t('donate.later')}</Button>
        </>
      }
    >
      <p className="text-[11px] text-neutral-500">{t('donate.footer')}</p>
    </Dialog>
  <AuthGate forceOpenSignal={authGateOpenSignal} onResolved={useCallback((u, data) => {
      setUser(u);
      if (data) {
        let nextProfile: UserProfile = emptyProfile;
        if (Array.isArray(data.entries) && hasLegacyEntries(data.entries)) {
          // Pre-migration Firestore doc: split the mixed entries array once,
          // then immediately push the cleaned shape back so this device
          // stops re-splitting on every future load.
          const split = splitLegacyEntries(data.entries);
          nextProfile = { ...emptyProfile, ...(data.profile || {}), ...split.profile };
          const nextLanguages = data.languages && data.languages.length ? data.languages : split.languages;
          setProfile(nextProfile);
          setLanguages(nextLanguages);
          setEntries(split.entries);
          saveUserDataIfChanged(u.uid, {
            entries: split.entries, profile: nextProfile, languages: nextLanguages,
            jobDescription: data.jobDescription, format: data.format,
          }).catch(() => {});
        } else {
          if (Array.isArray(data.entries)) setEntries(data.entries as ResumeEntry[]);
          if (data.profile) {
            nextProfile = { ...emptyProfile, ...data.profile };
            setProfile(nextProfile);
          }
          if (data.languages) setLanguages(data.languages);
        }
        if (nextProfile.fullName && nextProfile.email) setOnboardingComplete(true);
        if (data.jobDescription) setJobDescription(data.jobDescription);
        if (data.format === 'latex' || data.format === 'word') setFormat(data.format);
      }
    }, [])} />
    {
      geoLocation?.isArgentina && (
      <div className="max-w-5xl mx-auto pointer-events-auto">
        <AdBanner
          lightSrc="/Lannis banner - light.png"
          darkSrc="/Lannis banner - dark.png"
          alt="Lannis"
          href="https://lannis.app?utm_source=web&utm_medium=banner&utm_campaign=august12&utm_id=better-resume"
          className="shadow-lg"
        />
      </div>
      )
    }
      
  <Footer geoLocation={geoLocation} onDonateClick={setShowDonate} />
  </div>
  );
}
