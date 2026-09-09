import { z } from 'zod';
import { EDUCATION_TYPES, EXPERIENCE_TYPES } from '../../types';
import type { EntryType } from '../../types';
import { MONTH_YEAR_RE } from './monthYear';

/** Translation function shape, so every validation message is localized at build time
 * instead of leaking English zod defaults into the Spanish UI. */
export type Translate = (key: string) => string;

export const personalInfoSchema = (t: Translate) => z.object({
  fullName: z.string().trim().min(1, t('validation.fullName.required')),
  email: z.string().trim().min(1, t('validation.email.required')).email(t('validation.email.invalid')),
  phone: z.string().optional(),
  address: z.string().optional(),
});

const monthYearOrPresent = (t: Translate) => z
  .string()
  .optional()
  .refine((v) => !v || v.toLowerCase() === 'present' || MONTH_YEAR_RE.test(v), {
    message: t('validation.date.invalid'),
  });

/** MM/YYYY -> a comparable number (YYYY * 12 + month). */
function monthYearSortKey(v: string): number {
  const [mm, yyyy] = v.split('/');
  return Number(yyyy) * 12 + Number(mm);
}

/** Cross-field check that `end` isn't chronologically before `start`, reported on the
 * `end` field. Both sides are optional/"present"-aware already via monthYearOrPresent,
 * so this only fires when both are concrete MM/YYYY values. */
const dateOrderCheck = (data: { start?: string; end?: string }) => {
  const { start, end } = data;
  if (!start || !end) return true;
  if (start.toLowerCase() === 'present' || end.toLowerCase() === 'present') return true;
  if (!MONTH_YEAR_RE.test(start) || !MONTH_YEAR_RE.test(end)) return true;
  return monthYearSortKey(end) >= monthYearSortKey(start);
};
const dateOrderCheckOptions = (t: Translate) => ({ message: t('validation.date.order'), path: ['end'] });

export const educationEntrySchema = (t: Translate) => z.object({
  type: z.enum(EDUCATION_TYPES as [EntryType, ...EntryType[]]),
  company: z.string().trim().min(1, t('validation.institution.required')),
  role: z.string().trim().min(1, t('validation.degree.required')),
  location: z.string().optional(),
  start: monthYearOrPresent(t),
  end: monthYearOrPresent(t),
  description: z.string().optional(),
}).refine(dateOrderCheck, dateOrderCheckOptions(t));

export const experienceEntrySchema = (t: Translate) => z.object({
  type: z.enum(EXPERIENCE_TYPES as [EntryType, ...EntryType[]]),
  company: z.string().trim().min(1, t('validation.company.required')),
  role: z.string().trim().min(1, t('validation.role.required')),
  location: z.string().optional(),
  start: monthYearOrPresent(t),
  end: monthYearOrPresent(t),
  description: z.string().optional(),
}).refine(dateOrderCheck, dateOrderCheckOptions(t));

export const languageEntrySchema = (t: Translate) => z.object({
  name: z.string().trim().min(1, t('validation.language.required')),
  proficiency: z.string().trim().min(1, t('validation.proficiency.required')),
});

/** Collects the first zod issue per top-level field into `{ field: message }`. */
export function issuesToFieldErrors(issues: { path: PropertyKey[]; message: string }[]): Record<string, string> {
  const fieldErrors: Record<string, string> = {};
  for (const issue of issues) {
    const key = issue.path[0];
    if (typeof key === 'string' && !fieldErrors[key]) fieldErrors[key] = issue.message;
  }
  return fieldErrors;
}

/** After a failed validation, bring the first invalid control into view (the entry
 * dialog scrolls, so on a phone the error can otherwise sit below the fold). */
export function scrollToFirstInvalid(root: HTMLElement | null) {
  if (!root) return;
  requestAnimationFrame(() => {
    const el = root.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    try { el.focus({ preventScroll: true }); } catch { /* ignore */ }
  });
}
