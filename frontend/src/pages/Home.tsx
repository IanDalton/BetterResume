import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadJobsJson, generateResumeStream, buildJobsFromEntries, resolveProfilePictureUrl, saveProfile, saveLanguages, MERCADOPAGO_URL } from '../services';
import { EXPERIENCE_TYPES, LanguageEntry, ResumeEntry, UserProfile, emptyProfile } from '../types';
import { ProfileEditor } from '../components/entries';
import { SaveStatus } from '../components/entries/SaveStatusIndicator';
import { Footer } from '../components/Footer';
import { AuthGate, UserBar, getOrCreateGuestId } from '../components/AuthGate';
import { AdBanner } from '../components/AdBanner';
import { ProfilePictureUploader } from '../components/ProfilePictureUploader';
import { logout, saveUserDataIfChanged } from '../services/firebase';
import { splitLegacyEntries, hasLegacyEntries, loadLocalDataWithMigration } from '../services/legacyMigration';
import { useI18n, availableLanguages } from '../i18n';
import { initAnalytics, pageView, setupErrorTracking, trackConsole, trackEvent } from '../services/analytics';
import { detectCountry } from '../services/geolocation';
import { useDonationNudges } from '../hooks/useDonationNudges';
import { Dialog, Button, Select, Spinner, ConfirmDialog, FormField, Textarea } from '../components/ui';
import { useToast } from '../components/ui/use-toast';


/** Backend stream stages -> the phrase the user sees. Anything unmapped keeps the
 * previous phrase, so internals never leak into the progress dialog. */
const STAGE_PHRASES: Record<string, string> = {
  csv_info: 'progress.stage.reading',
  invoking_graph: 'progress.stage.choosing',
  graph_complete: 'progress.stage.organizing',
  parsed: 'progress.stage.organizing',
  translating: 'progress.stage.translating',
  translated: 'progress.stage.translating',
  writing_file: 'progress.stage.writing',
  done: 'progress.stage.done',
};

const StepHeading: React.FC<{ id: string; title: string; hint: string }> = ({ id, title, hint }) => (
  <div className="mb-4">
    <h2 id={id} className="text-xl font-semibold text-neutral-900 dark:text-neutral-100">{title}</h2>
    <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">{hint}</p>
  </div>
);

export function Home() {
  const { t, lang, setLang } = useI18n();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [profile, setProfile] = useState<UserProfile>(() => loadLocalDataWithMigration().profile);
  const [languages, setLanguages] = useState<LanguageEntry[]>(() => loadLocalDataWithMigration().languages);
  const [entries, setEntries] = useState<ResumeEntry[]>(() => loadLocalDataWithMigration().entries);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [user, setUser] = useState<{mode:'auth'|'guest'; uid:string; email?:string} | null>(null);
  const [authGateOpenSignal, setAuthGateOpenSignal] = useState(0);
  // Reuse the stored guest id (it keys the profile photo on the backend); only mint a
  // new one when none exists. AuthGate applies the same rule once auth state resolves.
  const [guestId] = useState(() => getOrCreateGuestId());
  const userId = user?.uid || guestId;
  const [loading, setLoading] = useState(false);
  const [downloadLinks, setDownloadLinks] = useState<{pdf:string; source:string}|null>(null);
  const [profilePictureUrl, setProfilePictureUrl] = useState<string | null>(null);
  const [jobDescription, setJobDescription] = useState(() => {
    try { return localStorage.getItem('br.jobDescription') || ''; } catch { return ''; }
  });
  const [format, setFormat] = useState<'latex' | 'word'>(() => {
    try { const f = localStorage.getItem('br.format'); if (f === 'word' || f === 'latex') return f; } catch {}
    return 'word';
  });
  const [stage, setStage] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<null | 'pdf' | 'source'>(null);
  const [showGenModal, setShowGenModal] = useState(false);
  const [generateAttempted, setGenerateAttempted] = useState(false);
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [genStartAt, setGenStartAt] = useState<number | null>(null);
  const [firstEventAt, setFirstEventAt] = useState<number | null>(null);
  const [resumeCount, setResumeCount] = useState<number>(()=>{
    try { const v = localStorage.getItem('br.resumeCount'); return v? parseInt(v)||0 : 0; } catch { return 0; }
  });
  const [geoLocation, setGeoLocation] = useState<{isOutsideUS: boolean; isArgentina: boolean; country: string} | null>(null);
  const pdfSectionRef = React.useRef<HTMLDivElement | null>(null);
  const profileSectionRef = React.useRef<HTMLDivElement | null>(null);
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
  // only on Generate -- closes the "navigate away mid-edit" data-loss gap.
  // Work-experience entries still sync only via performUpload (that pipeline
  // re-ingests pgvector documents and is too expensive to run on every
  // keystroke), which is why the indicator says "Profile saved", not "Saved".
  const autosaveTimer = useRef<number | null>(null);
  const lastSynced = useRef<{ userId: string; profile: string; languages: string } | null>(null);
  useEffect(() => {
    const profileJson = JSON.stringify(profile);
    const languagesJson = JSON.stringify(languages);
    if (!lastSynced.current) {
      // First run is initial hydration, not an edit -- record it, don't save.
      lastSynced.current = { userId, profile: profileJson, languages: languagesJson };
      return;
    }
    if (autosaveTimer.current) window.clearTimeout(autosaveTimer.current);
    setSaveStatus('saving');
    autosaveTimer.current = window.setTimeout(async () => {
      try {
        const prev = lastSynced.current!;
        const userChanged = prev.userId !== userId;
        const tasks: Promise<void>[] = [];
        if (userChanged || prev.profile !== profileJson) tasks.push(saveProfile(userId, profile));
        if (userChanged || prev.languages !== languagesJson) tasks.push(saveLanguages(userId, languages));
        await Promise.all(tasks);
        lastSynced.current = { userId, profile: profileJson, languages: languagesJson };
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

  useEffect(() => { try { localStorage.setItem('br.jobDescription', jobDescription); } catch {} }, [jobDescription]);
  useEffect(() => { try { localStorage.setItem('br.format', format); } catch {} }, [format]);
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

  // Single source of truth for donation nudges (see useDonationNudges for why this
  // replaces what used to be three independent toast triggers plus a modal trigger).
  const donationNudges = useDonationNudges({ resumeCount, busy: showGenModal });
  const isArgentina = !!geoLocation?.isArgentina;
  const goDonate = useCallback(() => {
    if (isArgentina) window.open(MERCADOPAGO_URL, '_blank', 'noopener');
    else navigate('/donate');
  }, [isArgentina, navigate]);

  // The donation nudge is a regular toast (one toast system, one corner) with a
  // "Donate" action; closing it in any way records the cooldown.
  useEffect(() => {
    if (!donationNudges.showToast) return;
    toast({
      title: t('donate.toast.title'),
      description: t('donate.toast.body'),
      durationMs: 15000,
      action: { label: t('donate.toast.cta'), onClick: goDonate },
      onDismiss: donationNudges.dismissToast,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [donationNudges.showToast]);

  const addEntry = (entry: ResumeEntry) => setEntries(p => [...p, entry]);
  const updateEntry = (index: number, entry: ResumeEntry) => setEntries(p => p.map((e,i)=> i===index? entry : e));
  const removeEntry = (index: number) => setEntries(p => p.filter((_,i)=> i!==index));

  // Internal upload helper used by generation. Does not manage loading state.
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

  const genAbortRef = useRef<AbortController | null>(null);

  const handleCancelGenerate = () => {
    genAbortRef.current?.abort();
  };

  // Require basic personal info (name + email) and at least one experience entry.
  const hasPersonalBasics = !!(profile.fullName && profile.email);
  const hasExperience = entries.some(e => EXPERIENCE_TYPES.includes(e.type));
  const hasJobDescription = jobDescription.trim().length > 0;
  const missingHint = !hasPersonalBasics ? t('validation.personal')
    : !hasExperience ? t('validation.experience')
    : !hasJobDescription ? t('validation.jobDescription')
    : null;

  const handleGenerate = async () => {
    if (missingHint) {
      // The hint under the button turns into an error and the page scrolls to where
      // the missing piece lives, instead of a silently disabled button.
      setGenerateAttempted(true);
      if (!hasPersonalBasics || !hasExperience) profileSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    const abortController = new AbortController();
    genAbortRef.current = abortController;
    try {
      setLoading(true);
      setGenStartAt(Date.now());
      setFirstEventAt(null);
      try { trackEvent('resume_generate_start', { format, entries: entries.length, has_job: !!jobDescription, auth: user?.mode==='auth' }); } catch {}
      setStage(null);
      // Clear previous outputs so UI doesn't show outdated preview while regenerating
      setDownloadLinks(null);
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
        if (STAGE_PHRASES[evt.stage]) setStage(evt.stage);
        if (evt.stage === 'error') {
          try { trackEvent('resume_generate_error', { message: evt.message||'error' }); } catch {}
        }
      }, abortController.signal);
      if (res.files) setDownloadLinks(res.files);
      try {
        const dur = genStartAt ? (Date.now() - genStartAt) : undefined;
        const first = genStartAt && firstEventAt ? (firstEventAt - genStartAt) : undefined;
        trackEvent('resume_generate_success', { format, duration_ms: dur, first_event_ms: first });
      } catch {}
      // Increment successful generation count; useDonationNudges reacts to this itself.
      setResumeCount(c => {
        const next = c + 1;
        try { localStorage.setItem('br.resumeCount', String(next)); } catch {}
        return next;
      });
    } catch (e: any) {
      if (e?.name !== 'AbortError') {
        // Never surface the backend's message: the app's own copy says what to do,
        // and the toast offers a retry.
        toast({
          title: t('generate.error.failed'),
          variant: 'error',
          durationMs: 10000,
          action: { label: t('generate.error.retry'), onClick: () => { void handleGenerate(); } },
        });
      }
    } finally {
      genAbortRef.current = null;
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
        throw new Error(`Download failed (${res.status})`);
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
    } catch {
      toast({ title: t('download.error.failed'), variant: 'error' });
    } finally {
      setDownloading(null);
    }
  };

  const [pdfUrl, setPdfUrl] = useState<string|null>(null);
  // Tracks a blob URL *we* created via createObjectURL, so we can revoke it
  // (and only it — never a caller-supplied blob:/data: URL) on the next run/unmount.
  const createdPdfBlobUrlRef = useRef<string | null>(null);

  useEffect(()=>{
    if (downloadLinks?.pdf && pdfSectionRef.current) {
      // Scroll PDF section into view after generation completes
      pdfSectionRef.current.scrollIntoView({behavior:'smooth'});
    }

    const revokeOwnedBlobUrl = () => {
      if (createdPdfBlobUrlRef.current) {
        URL.revokeObjectURL(createdPdfBlobUrlRef.current);
        createdPdfBlobUrlRef.current = null;
      }
    };

    // Fetch PDF as blob to bypass CSP frame-ancestors restrictions
    let active = true;
    revokeOwnedBlobUrl();
    if (downloadLinks?.pdf) {
      if (downloadLinks.pdf.startsWith('blob:') || downloadLinks.pdf.startsWith('data:')) {
        setPdfUrl(downloadLinks.pdf);
      } else {
        fetch(downloadLinks.pdf)
          .then(res => res.blob())
          .then(blob => {
            if (active) {
              const url = URL.createObjectURL(blob);
              createdPdfBlobUrlRef.current = url;
              setPdfUrl(url);
            }
          })
          .catch(err => {
            console.error('Failed to fetch PDF blob:', err);
            if (active) {
              setPdfUrl(null);
              toast({ title: t('preview.pdf.fetchFailed'), variant: 'error' });
            }
          });
      }
    } else {
      setPdfUrl(null);
    }
    return () => {
      active = false;
      revokeOwnedBlobUrl();
    };
  }, [downloadLinks?.pdf]);

  const handleLogoutConfirmed = async () => {
    await logout();
    // The signed-out account's profile/languages/entries must never ride along
    // into the guest identity: userId flips from the auth uid to `guestId` on
    // the very next render, and the autosave effect below persists whatever
    // `profile`/`languages` currently hold under whatever `userId` currently
    // is. Blank the in-memory state back to a fresh guest first...
    setProfile(emptyProfile);
    setLanguages([]);
    setEntries([]);
    setJobDescription('');
    // ...and mark that blank state as already-synced for the guest id, so the
    // userId transition reads as a fresh hydration (like the initial-mount
    // case) instead of an edit the autosave effect needs to push.
    lastSynced.current = { userId: guestId, profile: JSON.stringify(emptyProfile), languages: JSON.stringify([]) };
    setUser(null);
  };

  const stagePhrase = stage ? t(STAGE_PHRASES[stage]) : t('progress.starting');

  // Returning users with an already-generate-ready profile shouldn't have to
  // scroll past five profile cards on every visit just to paste a new job
  // description -- promote "El puesto" above the profile section once the
  // profile already satisfies Generate's own requirements.
  const profileReadyForJob = hasPersonalBasics && hasExperience;

  const profileSection = (
    <section ref={profileSectionRef} aria-labelledby="step-profile" className="scroll-mt-4">
      <StepHeading id="step-profile" title={t('home.step.profile.title')} hint={t('home.step.profile.hint')} />
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
        saveStatus={saveStatus}
      >
        <ProfilePictureUploader userId={userId} imageUrl={profilePictureUrl} onUploaded={handleProfileUploaded} />
      </ProfileEditor>
    </section>
  );

  const jobSection = (
    <section aria-labelledby="step-job">
      <StepHeading id="step-job" title={t('home.step.job.title')} hint={t('home.step.job.hint')} />
      <div className="space-y-5 rounded-xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <FormField label={t('job.description.label')} htmlFor="job-description" required>
          <Textarea
            id="job-description"
            className="w-full min-h-[200px]"
            value={jobDescription}
            onChange={e => setJobDescription(e.target.value)}
            placeholder={t('job.description.placeholder')}
            invalid={generateAttempted && !hasJobDescription}
          />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t('format')} hint={t('format.hint')}>
            <Select
              value={format}
              aria-label={t('format')}
              onValueChange={(v) => setFormat(v as any)}
              options={[
                { value: 'word', label: t('format.word') },
                { value: 'latex', label: t('format.latex') },
              ]}
            />
          </FormField>
          <div className="flex flex-col gap-1">
            <label className="flex min-h-[44px] items-center gap-2 text-sm text-neutral-700 dark:text-neutral-300">
              <input
                type="checkbox"
                className="h-4 w-4 accent-red-600"
                checked={includeProfilePicture && !!profilePictureUrl}
                onChange={e => setIncludeProfilePicture(e.target.checked)}
                disabled={!profilePictureUrl}
              />
              <span className={!profilePictureUrl ? 'text-neutral-400 dark:text-neutral-500' : ''}>{t('profile.toggle')}</span>
            </label>
            {!profilePictureUrl && (
              <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('profile.toggle.disabled')}</p>
            )}
          </div>
        </div>
        <div className="space-y-2">
          <Button size="md" className="w-full sm:w-auto sm:min-w-[16rem]" loading={loading} onClick={handleGenerate}>
            {t('generate.resume')}
          </Button>
          {loading ? (
            <p className="flex items-center gap-2 text-sm text-neutral-600 dark:text-neutral-400">
              <Spinner size="sm" /> {t('validation.generating')}
            </p>
          ) : missingHint ? (
            <p
              className={generateAttempted ? 'text-sm text-red-600 dark:text-red-400' : 'text-sm text-neutral-500 dark:text-neutral-400'}
              role={generateAttempted ? 'alert' : undefined}
            >
              {missingHint}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );

  return (
  <div className="max-w-5xl mx-auto p-4 font-sans">
      <header className="mb-8 flex flex-wrap items-center gap-x-4 gap-y-3">
        <img src="/logo2.png" alt={t('app.title')} className="h-12 w-auto select-none sm:h-14" draggable={false} />
        <p className="hidden min-w-0 flex-1 text-sm leading-snug text-neutral-600 dark:text-neutral-400 md:block">{t('app.tagline')}</p>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select
            value={lang}
            aria-label={t('app.language')}
            onValueChange={(v) => setLang(v as any)}
            options={availableLanguages.map(l => ({ value: l.code, label: t(l.labelKey) }))}
          />
          {user && <UserBar user={user} onLogout={() => setConfirmLogout(true)} onSignInRequest={() => setAuthGateOpenSignal(s=>s+1)} />}
        </div>
      </header>

      <main className="space-y-12">
        {profileReadyForJob ? (
          <>
            {jobSection}
            {profileSection}
          </>
        ) : (
          <>
            {profileSection}
            {jobSection}
          </>
        )}

        {downloadLinks && (
          <section ref={pdfSectionRef} aria-labelledby="step-resume" className="scroll-mt-4">
            <StepHeading id="step-resume" title={t('home.step.resume.title')} hint={t('home.step.resume.hint')} />
            <div className="space-y-4">
              <p className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-800 dark:border-violet-800 dark:bg-violet-900/30 dark:text-violet-200">
                {t('preview.ai.notice')}
              </p>
              <div className="relative aspect-[8.5/11] w-full overflow-hidden rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
                {pdfUrl ? (
                  <iframe title={t('preview.title')} src={pdfUrl} className="h-full w-full" />
                ) : (
                  <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-neutral-500">{t('preview.pdf.fetchFailed')}</div>
                )}
              </div>
              <div className="flex flex-wrap gap-3">
                {downloadLinks.pdf && (
                  <Button variant="primary" className="w-full sm:w-auto" loading={downloading==='pdf'} onClick={()=>handleDownload('pdf')}>
                    {downloading==='pdf' ? t('download.downloading') : t('download.pdf')}
                  </Button>
                )}
                {downloadLinks.source && (
                  <Button variant="secondary" className="w-full sm:w-auto" loading={downloading==='source'} onClick={()=>handleDownload('source')}>
                    {downloading==='source' ? t('download.preparing') : (format === 'latex' ? t('download.source.latex') : t('download.source.word'))}
                  </Button>
                )}
              </div>
            </div>
          </section>
        )}
      </main>

      <Dialog
        open={showGenModal}
        onOpenChange={() => {}}
        hideClose
        title={t('modal.building.title')}
        description={t('modal.building.subtitle')}
        footer={<Button variant="secondary" size="sm" onClick={handleCancelGenerate}>{t('button.cancelGeneration')}</Button>}
      >
        <div className="space-y-3" aria-live="polite">
          <div className="h-2 w-full overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
            <div className="h-full w-full bg-[length:200%_100%] bg-gradient-to-r from-red-500 via-rose-300 to-red-500 animate-progressMove" />
          </div>
          <p className="flex items-center gap-2 text-sm text-neutral-700 dark:text-neutral-300">
            <Spinner size="sm" /> {stagePhrase}
          </p>
        </div>
      </Dialog>

      <Dialog
        open={donationNudges.showModal}
        onOpenChange={(open) => { if (!open) donationNudges.dismissModal(); }}
        title={t('donate.title')}
        description={t('donate.body')}
        footer={
          <>
            <Button variant="secondary" onClick={donationNudges.dismissModal}>{t('donate.later')}</Button>
            <Button variant="primary" onClick={() => { donationNudges.dismissModal(); goDonate(); }}>{t('donate.cta')}</Button>
          </>
        }
      >
        <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('donate.footer')}</p>
      </Dialog>

      <ConfirmDialog
        open={confirmLogout}
        onOpenChange={setConfirmLogout}
        title={t('confirm.logout.title')}
        description={t('confirm.logout.body')}
        confirmLabel={t('confirm.logout.confirm')}
        cancelLabel={t('button.cancel')}
        destructive={false}
        onConfirm={() => { void handleLogoutConfirmed(); }}
      />

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
          if (data.jobDescription) setJobDescription(data.jobDescription);
          if (data.format === 'latex' || data.format === 'word') setFormat(data.format);
        }
      }, [])} />

      {geoLocation?.isArgentina && (
        <div className="mt-12">
          <AdBanner
            lightSrc="/Lannis banner - light.png"
            darkSrc="/Lannis banner - dark.png"
            alt="Lannis"
            href="https://lannis.app?utm_source=web&utm_medium=banner&utm_campaign=august12&utm_id=better-resume"
            className="shadow-lg"
          />
        </div>
      )}

      <Footer geoLocation={geoLocation} />
  </div>
  );
}
