import React, { useRef, useState } from 'react';
import { LanguageEntry, ResumeEntry, UserProfile } from '../../types';
import { Dialog, Button, Spinner } from '../ui';
import { useToast } from '../ui/use-toast';
import { importResumePdf, ResumeImportResult } from '../../services/api';
import { importedEntryToResumeEntry } from '../../services/resumeImport';
import { useI18n } from '../../i18n';

interface Props {
  userId: string;
  currentProfile: UserProfile;
  onProfileChange: (p: UserProfile) => void;
  currentLanguages: LanguageEntry[];
  onLanguagesChange: (l: LanguageEntry[]) => void;
  onAddEntry: (e: ResumeEntry) => void;
}

type Step = 'upload' | 'parsing' | 'review';

const MAX_BYTES = 10 * 1024 * 1024;

interface Selection {
  profile: Record<string, boolean>;
  links: boolean[];
  experience: boolean[];
  education: boolean[];
  languages: boolean[];
}

const EMPTY_SELECTION: Selection = { profile: {}, links: [], experience: [], education: [], languages: [] };

export const ResumeImportDialog: React.FC<Props> = ({
  userId, currentProfile, onProfileChange, currentLanguages, onLanguagesChange, onAddEntry,
}) => {
  const { t } = useI18n();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>('upload');
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ResumeImportResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selected, setSelected] = useState<Selection>(EMPTY_SELECTION);

  const reset = () => {
    setStep('upload');
    setError(null);
    setResult(null);
    setSelected(EMPTY_SELECTION);
  };

  const openDialog = () => { reset(); setOpen(true); };

  const handleFile = async (file: File) => {
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) { setError(t('resume.import.dropzone')); return; }
    if (file.size > MAX_BYTES) { setError('File too large (max 10 MB).'); return; }
    setStep('parsing');
    setError(null);
    try {
      const parsed = await importResumePdf(userId, file);
      setResult(parsed);
      const fields: Record<string, boolean> = {};
      if (parsed.profile.full_name) fields.full_name = !currentProfile.fullName;
      if (parsed.profile.email) fields.email = !currentProfile.email;
      if (parsed.profile.phone) fields.phone = !currentProfile.phone;
      if (parsed.profile.location) fields.address = !currentProfile.address;
      setSelected({
        profile: fields,
        links: parsed.profile.links.map(() => true),
        experience: parsed.experience.map(() => true),
        education: parsed.education.map(() => true),
        languages: parsed.languages.map(() => true),
      });
      setStep('review');
    } catch (e: any) {
      setError(e.message || 'Import failed');
      setStep('upload');
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const toggleAt = (section: 'links' | 'experience' | 'education' | 'languages', i: number) =>
    setSelected((s) => ({ ...s, [section]: s[section].map((v, idx) => (idx === i ? !v : v)) }));
  const toggleProfileField = (key: string) =>
    setSelected((s) => ({ ...s, profile: { ...s.profile, [key]: !s.profile[key] } }));

  const confirmImport = () => {
    if (!result) return;
    const profileUpdates: Partial<UserProfile> = {};
    if (selected.profile.full_name && result.profile.full_name) profileUpdates.fullName = result.profile.full_name;
    if (selected.profile.email && result.profile.email) profileUpdates.email = result.profile.email;
    if (selected.profile.phone && result.profile.phone) profileUpdates.phone = result.profile.phone;
    if (selected.profile.address && result.profile.location) profileUpdates.address = result.profile.location;
    const newLinks = result.profile.links.filter((_, i) => selected.links[i]);
    if (Object.keys(profileUpdates).length || newLinks.length) {
      onProfileChange({ ...currentProfile, ...profileUpdates, links: [...currentProfile.links, ...newLinks] });
    }
    result.experience.filter((_, i) => selected.experience[i]).forEach((e) => onAddEntry(importedEntryToResumeEntry(e)));
    result.education.filter((_, i) => selected.education[i]).forEach((e) => onAddEntry(importedEntryToResumeEntry(e)));
    const newLanguages = result.languages.filter((_, i) => selected.languages[i]);
    if (newLanguages.length) onLanguagesChange([...currentLanguages, ...newLanguages]);
    toast({ title: t('resume.import.success'), variant: 'success' });
    setOpen(false);
  };

  const selectedCount =
    selected.experience.filter(Boolean).length +
    selected.education.filter(Boolean).length +
    selected.languages.filter(Boolean).length +
    selected.links.filter(Boolean).length +
    Object.values(selected.profile).filter(Boolean).length;

  return (
    <>
      <Button variant="secondary" size="sm" onClick={openDialog}>{t('resume.import.button')}</Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={t('resume.import.title')}
        size="lg"
        footer={
          step === 'review' ? (
            <>
              <Button variant="secondary" onClick={reset}>{t('resume.import.tryAgain')}</Button>
              <Button variant="primary" disabled={selectedCount === 0} onClick={confirmImport}>
                {t('resume.import.confirm')} ({selectedCount})
              </Button>
            </>
          ) : (
            <Button variant="secondary" onClick={() => setOpen(false)}>{t('resume.import.cancel')}</Button>
          )
        }
      >
        {step === 'upload' && (
          <div className="space-y-4">
            <p className="text-sm text-neutral-600 dark:text-neutral-400">{t('resume.import.upload.hint')}</p>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              className={
                'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-10 text-center text-sm transition-colors ' +
                (dragOver
                  ? 'border-red-500 bg-red-50 dark:bg-red-900/20'
                  : 'border-neutral-300 text-neutral-500 hover:border-neutral-400 dark:border-neutral-700 dark:text-neutral-400')
              }
            >
              <span aria-hidden className="text-2xl">📄</span>
              <span>{t('resume.import.dropzone')}</span>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
            />
            {error && <p className="text-sm text-red-500">{error}</p>}
          </div>
        )}

        {step === 'parsing' && (
          <div className="flex flex-col items-center gap-3 py-10 text-sm text-neutral-600 dark:text-neutral-400">
            <Spinner size="lg" />
            <p>{t('resume.import.parsing')}</p>
          </div>
        )}

        {step === 'review' && result && (
          <div className="max-h-[60vh] space-y-6 overflow-y-auto pr-1">
            <p className="text-sm text-neutral-600 dark:text-neutral-400">{t('resume.import.review.hint')}</p>
            {result.warnings.length > 0 && (
              <ul className="list-inside list-disc rounded-lg bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-900/20 dark:text-amber-300">
                {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}

            <section>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">{t('resume.import.section.profile')}</h4>
              <div className="space-y-2 text-sm">
                {([
                  ['full_name', result.profile.full_name],
                  ['email', result.profile.email],
                  ['phone', result.profile.phone],
                  ['address', result.profile.location],
                ] as const).map(([key, value]) => value && (
                  <label key={key} className="flex items-center gap-2">
                    <input type="checkbox" className="accent-red-600" checked={!!selected.profile[key]}
                      onChange={() => toggleProfileField(key)} />
                    {value}
                  </label>
                ))}
                {result.profile.links.map((link, i) => (
                  <label key={i} className="flex items-center gap-2">
                    <input type="checkbox" className="accent-red-600" checked={!!selected.links[i]}
                      onChange={() => toggleAt('links', i)} />
                    <span className="truncate">{link.kind}: {link.url}</span>
                  </label>
                ))}
              </div>
            </section>

            <ReviewEntrySection
              title={t('resume.import.section.experience')}
              entries={result.experience}
              selected={selected.experience}
              onToggle={(i) => toggleAt('experience', i)}
              emptyLabel={t('resume.import.none')}
            />
            <ReviewEntrySection
              title={t('resume.import.section.education')}
              entries={result.education}
              selected={selected.education}
              onToggle={(i) => toggleAt('education', i)}
              emptyLabel={t('resume.import.none')}
            />

            <section>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">{t('resume.import.section.languages')}</h4>
              {result.languages.length === 0 ? (
                <p className="text-sm text-neutral-500">{t('resume.import.none')}</p>
              ) : (
                <div className="space-y-2 text-sm">
                  {result.languages.map((l, i) => (
                    <label key={i} className="flex items-center gap-2">
                      <input type="checkbox" className="accent-red-600" checked={!!selected.languages[i]}
                        onChange={() => toggleAt('languages', i)} />
                      <span className="font-semibold">{l.name}</span>{l.proficiency ? ` — ${l.proficiency}` : ''}
                    </label>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
      </Dialog>
    </>
  );
};

const ReviewEntrySection: React.FC<{
  title: string;
  entries: { role?: string | null; company: string; location?: string | null; start_date?: string | null; end_date?: string | null; description: string }[];
  selected: boolean[];
  onToggle: (i: number) => void;
  emptyLabel: string;
}> = ({ title, entries, selected, onToggle, emptyLabel }) => (
  <section>
    <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h4>
    {entries.length === 0 ? (
      <p className="text-sm text-neutral-500">{emptyLabel}</p>
    ) : (
      <div className="space-y-2">
        {entries.map((e, i) => (
          <label
            key={i}
            className="flex items-start gap-2 rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-sm dark:border-neutral-800 dark:bg-neutral-800/50"
          >
            <input type="checkbox" className="mt-1 accent-red-600" checked={!!selected[i]} onChange={() => onToggle(i)} />
            <span>
              <span className="font-semibold">{e.role}{e.company ? ` @ ${e.company}` : ''}</span>
              {(e.start_date || e.end_date) && (
                <span className="ml-2 text-xs text-neutral-500">{e.start_date || '—'} → {e.end_date || 'Present'}</span>
              )}
              {e.description && <p className="mt-1 whitespace-pre-wrap text-xs text-neutral-600 dark:text-neutral-400">{e.description}</p>}
            </span>
          </label>
        ))}
      </div>
    )}
  </section>
);
