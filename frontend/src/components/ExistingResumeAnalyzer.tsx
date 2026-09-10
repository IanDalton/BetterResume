import React, { useRef, useState } from 'react';
import { analyzeResumePdf, type PdfResumeAnalysis } from '../services/api';
import { useI18n } from '../i18n';
import { Button } from './ui';
import { useToast } from './ui/use-toast';
import { ResumeAnalysisPanel } from './ResumeAnalysisPanel';
import { trackEvent } from '../services/analytics';

interface Props {
  userId: string;
  jobDescription: string;
}

/** "Already have a resume?" -- upload a PDF and score it against the job
 * description without generating anything. Lives under the job description
 * box; the analysis it shows cannot be regenerated (no apply button). */
export function ExistingResumeAnalyzer({ userId, jobDescription }: Props) {
  const { t, lang } = useI18n();
  const { toast } = useToast();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PdfResumeAnalysis | null>(null);

  const run = async () => {
    if (!file || !jobDescription) return;
    setBusy(true);
    try { trackEvent('resume_pdf_analyze_start', {}); } catch {}
    try {
      const analysis = await analyzeResumePdf(userId, file, jobDescription, lang);
      setResult(analysis);
      try { trackEvent('resume_pdf_analyze_success', { ats: analysis.ats.score, review: !!analysis.review }); } catch {}
    } catch (e: any) {
      try { trackEvent('resume_pdf_analyze_error', { message: e?.message || 'error' }); } catch {}
      toast({ title: e?.message || t('analysis.error'), variant: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const pick = (f: File | null) => {
    setFile(f);
    setResult(null);
  };

  return (
    <div className="rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 p-4 space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-medium">{t('analysis.existing.title')}</p>
          <p className="text-xs text-neutral-600 dark:text-neutral-400">{t('analysis.existing.intro')}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
          />
          <Button variant="secondary" size="sm" onClick={() => inputRef.current?.click()} disabled={busy}>
            {file ? file.name : t('analysis.existing.choose')}
          </Button>
          <Button size="sm" loading={busy} disabled={busy || !file || !jobDescription} onClick={run}>
            {busy ? t('analysis.running') : t('analysis.existing.cta')}
          </Button>
        </div>
      </div>
      {!jobDescription && <p className="text-xs text-neutral-500">{t('analysis.existing.needsJob')}</p>}
      {result && (
        <div className="pt-2 space-y-3">
          {result.warnings.length > 0 && (
            <ul className="text-xs text-amber-700 dark:text-amber-300 list-disc list-inside">
              {result.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
          <ResumeAnalysisPanel analysis={result} resume={result.resume} />
        </div>
      )}
    </div>
  );
}
