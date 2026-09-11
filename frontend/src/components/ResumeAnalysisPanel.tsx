import React, { useEffect, useState } from 'react';
import type { AnalysisIssue, AnalysisRecommendation, AnalysisSeverity, ResumeAnalysis } from '../services/api';
import { useI18n } from '../i18n';
import { Button, Card, CardContent, cn } from './ui';

/** Score band colours shared by the tiles and the bars: green from 75, amber
 * from 50, red below. */
function band(score: number): 'good' | 'ok' | 'bad' {
  if (score >= 75) return 'good';
  if (score >= 50) return 'ok';
  return 'bad';
}

const bandText: Record<ReturnType<typeof band>, string> = {
  good: 'text-emerald-600 dark:text-emerald-400',
  ok: 'text-amber-600 dark:text-amber-400',
  bad: 'text-red-600 dark:text-red-400',
};

const bandBar: Record<ReturnType<typeof band>, string> = {
  good: 'bg-emerald-500',
  ok: 'bg-amber-500',
  bad: 'bg-red-500',
};

const severityClass: Record<AnalysisSeverity, string> = {
  high: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  medium: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  low: 'bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300',
};

function ScoreTile({ label, hint, score, previous }: { label: string; hint: string; score: number; previous?: number | null }) {
  const b = band(score);
  const delta = previous == null ? null : score - previous;
  return (
    <div className="flex-1 min-w-[12rem] rounded-lg border border-neutral-200 dark:border-neutral-800 p-4">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm font-medium">{label}</p>
        <p className={cn('text-3xl font-semibold tabular-nums', bandText[b])}>
          {score}<span className="text-base text-neutral-400">/100</span>
          {delta != null && (
            <span
              className={cn('ml-2 text-sm font-medium', delta > 0 ? 'text-emerald-600 dark:text-emerald-400' : delta < 0 ? 'text-red-600 dark:text-red-400' : 'text-neutral-400')}
              title={`${previous}`}
            >
              {delta > 0 ? `+${delta}` : delta === 0 ? '±0' : `${delta}`}
            </span>
          )}
        </p>
      </div>
      <div className="mt-2 h-2 rounded bg-neutral-100 dark:bg-neutral-800 overflow-hidden">
        <div className={cn('h-full rounded transition-all', bandBar[b])} style={{ width: `${score}%` }} />
      </div>
      <p className="mt-2 text-[11px] text-neutral-500 dark:text-neutral-400">{hint}</p>
    </div>
  );
}

function ScoreBar({ label, score }: { label: string; score: number }) {
  const b = band(score);
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-neutral-600 dark:text-neutral-300">{label}</span>
        <span className={cn('font-medium tabular-nums', bandText[b])}>{score}</span>
      </div>
      <div className="h-1.5 rounded bg-neutral-100 dark:bg-neutral-800 overflow-hidden">
        <div className={cn('h-full rounded', bandBar[b])} style={{ width: `${score}%` }} />
      </div>
    </div>
  );
}

function Chips({ items, tone }: { items: string[]; tone: 'matched' | 'missing' | 'add' }) {
  const toneClass = {
    matched: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800',
    missing: 'bg-neutral-50 text-neutral-600 border-neutral-200 dark:bg-neutral-800 dark:text-neutral-300 dark:border-neutral-700',
    add: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-300 dark:border-red-800',
  }[tone];
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <span key={`${item}-${i}`} className={cn('px-2 py-0.5 rounded-full border text-[11px]', toneClass)}>{item}</span>
      ))}
    </div>
  );
}

/** Label for an experience entry referenced by index: "Position · Company",
 * falling back to a 1-based number when the resume JSON is not available. */
function experienceLabel(resume: any, index: number | null | undefined): string | null {
  if (index == null || index < 0) return null;
  const entry = resume?.resume_section?.experience?.[index];
  if (!entry) return `#${index + 1}`;
  return [entry.position, entry.company].filter(Boolean).join(' · ') || `#${index + 1}`;
}

/** Scores of the analysis that preceded an "apply improvements"
 * regeneration, so the new tiles can show the delta. */
export interface PreviousScores {
  ats: number;
  review: number | null;
}

/** Plain-text change request for one recommendation, in the shape the
 * generation prompt's IMPROVEMENT REQUESTS block expects. */
export function recommendationToImprovement(rec: AnalysisRecommendation, resume: any): string {
  const target = rec.section === 'experience' ? experienceLabel(resume, rec.experience_index) : null;
  const where = target ? `${rec.section} (${target})` : rec.section;
  return `[${where}] ${rec.issue} Suggested change: ${rec.suggestion}`;
}

interface Props {
  analysis: ResumeAnalysis;
  /** The resume (ResumeOutputFormat JSON) the analysis is about. */
  resume: any;
  /** When set, the panel offers to regenerate the resume with the selected
   * recommendations (and keywords worth adding) applied. Absent for an
   * uploaded PDF, which cannot be regenerated. */
  onApplyImprovements?: (improvements: string[]) => void;
  applying?: boolean;
  previousScores?: PreviousScores | null;
}

export function ResumeAnalysisPanel({ analysis, resume, onApplyImprovements, applying, previousScores }: Props) {
  const { t } = useI18n();
  const { ats, review } = analysis;
  const recommendations = review?.recommendations ?? [];
  // Every recommendation starts selected; the user unticks what they disagree with.
  const [selected, setSelected] = useState<boolean[]>(() => recommendations.map(() => true));
  const [includeKeywords, setIncludeKeywords] = useState(true);
  useEffect(() => { setSelected(recommendations.map(() => true)); setIncludeKeywords(true); }, [analysis]);

  const canApply = !!onApplyImprovements && !!review;
  const selectedCount = selected.filter(Boolean).length + (includeKeywords && (review?.keywords_to_add.length ?? 0) > 0 ? 1 : 0);

  const buildImprovements = (): string[] => {
    const items = recommendations.filter((_, i) => selected[i]).map(rec => recommendationToImprovement(rec, resume));
    if (includeKeywords && review && review.keywords_to_add.length > 0) {
      items.push(`[keywords] Work these job-description terms into the summary, skills or bullets, only where the user's experience genuinely supports them: ${review.keywords_to_add.join(', ')}.`);
    }
    return items;
  };

  const issueText = (issue: AnalysisIssue) => {
    const base = t(`analysis.issue.${issue.kind}`).replace('{detail}', issue.detail);
    const label = experienceLabel(resume, issue.experience_index);
    return label ? `${label}: ${base}` : base;
  };

  const renderRecommendation = (rec: AnalysisRecommendation, i: number) => {
    const target = rec.section === 'experience' ? experienceLabel(resume, rec.experience_index) : null;
    return (
      <li key={i} className={cn('rounded-lg border p-3 space-y-1.5', canApply && !selected[i] ? 'border-neutral-100 dark:border-neutral-800/60 opacity-60' : 'border-neutral-200 dark:border-neutral-800')}>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          {canApply && (
            <input
              type="checkbox"
              className="accent-red-600"
              aria-label={t('analysis.apply.select')}
              checked={!!selected[i]}
              onChange={() => setSelected(s => s.map((v, j) => (j === i ? !v : v)))}
            />
          )}
          <span className={cn('px-1.5 py-0.5 rounded font-medium uppercase tracking-wide', severityClass[rec.severity])}>
            {t(`analysis.severity.${rec.severity}`)}
          </span>
          <span className="text-neutral-500">
            {t(`analysis.section.${rec.section}`)}{target ? ` · ${target}` : ''}
          </span>
        </div>
        <p className="text-sm text-neutral-800 dark:text-neutral-200">{rec.issue}</p>
        <p className="text-sm text-neutral-600 dark:text-neutral-400">
          <span className="font-medium text-neutral-700 dark:text-neutral-300">{t('analysis.suggestion')}: </span>{rec.suggestion}
        </p>
      </li>
    );
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-3">
        <ScoreTile label={t('analysis.ats.score')} hint={t('analysis.ats.hint')} score={ats.score} previous={previousScores?.ats} />
        {review && <ScoreTile label={t('analysis.review.score')} hint={t('analysis.review.hint')} score={review.scores.overall} previous={previousScores?.review} />}
      </div>

      {!review && (
        <p className="text-xs rounded-md border border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-200 px-3 py-2">
          {t('analysis.review.failed')}
        </p>
      )}

      <Card>
        <CardContent className="space-y-4">
          {ats.jd_looks_malformed && (
            <p className="text-xs rounded-md border border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-200 px-3 py-2">
              {t('analysis.jd.malformed')}
            </p>
          )}
          <ScoreBar label={t('analysis.coverage')} score={ats.keyword_coverage} />
          {ats.matched_keywords.length === 0 && ats.missing_keywords.length === 0 ? (
            <p className="text-xs text-neutral-500">{t('analysis.keywords.none')}</p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <p className="text-[11px] uppercase tracking-wide text-neutral-500">{t('analysis.keywords.matched')} ({ats.matched_keywords.length})</p>
                <Chips items={ats.matched_keywords} tone="matched" />
              </div>
              <div className="space-y-1.5">
                <p className="text-[11px] uppercase tracking-wide text-neutral-500">{t('analysis.keywords.missing')} ({ats.missing_keywords.length})</p>
                <Chips items={ats.missing_keywords} tone="missing" />
              </div>
            </div>
          )}
          {review && review.keywords_to_add.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[11px] uppercase tracking-wide text-neutral-500 flex items-center gap-2">
                {canApply && (
                  <input type="checkbox" className="accent-red-600" aria-label={t('analysis.apply.select')}
                    checked={includeKeywords} onChange={() => setIncludeKeywords(v => !v)} />
                )}
                {t('analysis.keywords.add')}
              </p>
              <Chips items={review.keywords_to_add} tone="add" />
            </div>
          )}
          <div className="space-y-1.5">
            <p className="text-[11px] uppercase tracking-wide text-neutral-500">{t('analysis.issues.title')}</p>
            {ats.issues.length === 0 ? (
              <p className="text-xs text-emerald-600 dark:text-emerald-400">{t('analysis.issues.none')}</p>
            ) : (
              <ul className="text-xs text-neutral-700 dark:text-neutral-300 list-disc list-inside space-y-0.5">
                {ats.issues.map((issue, i) => <li key={i}>{issueText(issue)}</li>)}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>

      {review && (
        <Card>
          <CardContent className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-[1fr_14rem]">
              <div>
                <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">{t('analysis.review.summary')}</p>
                <p className="text-sm text-neutral-800 dark:text-neutral-200">{review.summary}</p>
              </div>
              <div className="space-y-2">
                <ScoreBar label={t('analysis.review.relevance')} score={review.scores.relevance} />
                <ScoreBar label={t('analysis.review.quality')} score={review.scores.quality} />
                <ScoreBar label={t('analysis.review.coherence')} score={review.scores.coherence} />
              </div>
            </div>

            {review.strengths.length > 0 && (
              <div>
                <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">{t('analysis.strengths')}</p>
                <ul className="text-sm text-neutral-700 dark:text-neutral-300 list-disc list-inside space-y-0.5">
                  {review.strengths.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </div>
            )}

            <div>
              <p className="text-[11px] uppercase tracking-wide text-neutral-500 mb-2">{t('analysis.recommendations')}</p>
              {review.recommendations.length === 0 ? (
                <p className="text-sm text-neutral-500">{t('analysis.recommendations.none')}</p>
              ) : (
                <ul className="space-y-2">{review.recommendations.map(renderRecommendation)}</ul>
              )}
            </div>

            {canApply && (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between rounded-lg bg-neutral-50 dark:bg-neutral-800/60 p-3">
                <p className="text-xs text-neutral-600 dark:text-neutral-400">{t('analysis.apply.hint')}</p>
                <Button size="sm" loading={applying} disabled={applying || selectedCount === 0} onClick={() => onApplyImprovements!(buildImprovements())}>
                  {applying ? t('analysis.apply.running') : t('analysis.apply.cta').replace('{n}', String(selectedCount))}
                </Button>
              </div>
            )}

            {analysis.model && (
              <p className="text-[11px] text-neutral-400">{t('analysis.model')} {analysis.model}</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
