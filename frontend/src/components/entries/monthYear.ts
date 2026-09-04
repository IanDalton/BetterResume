/**
 * Pure helpers for the `MM/YYYY` date strings stored on entries (the same format the
 * backend and the entry list display use), kept free of React so they can be unit-tested.
 */

export const MONTH_YEAR_RE = /^(0[1-9]|1[0-2])\/(\d{4})$/;

export interface MonthYearParts {
  /** Two-digit month, `01`..`12`. */
  month: string;
  /** Four-digit year. */
  year: string;
}

export function isPresent(value?: string | null): boolean {
  return !!value && value.trim().toLowerCase() === 'present';
}

/** `03/2020` -> `{ month: '03', year: '2020' }`; anything else -> `null`. */
export function parseMonthYear(value?: string | null): MonthYearParts | null {
  if (!value) return null;
  const m = value.trim().match(MONTH_YEAR_RE);
  if (!m) return null;
  return { month: m[1], year: m[2] };
}

/** Builds `MM/YYYY` from the two select values. Returns `''` while either half is
 * still unset so a half-filled date never reaches the entry as a malformed string. */
export function formatMonthYear(month: string, year: string): string {
  if (!month || !year) return '';
  const mm = month.padStart(2, '0');
  if (!/^\d{4}$/.test(year) || !/^(0[1-9]|1[0-2])$/.test(mm)) return '';
  return `${mm}/${year}`;
}

/** Localized month names (`01`..`12` -> label), via Intl so no i18n keys are needed. */
export function monthOptions(locale: string): { value: string; label: string }[] {
  let fmt: Intl.DateTimeFormat | null = null;
  try { fmt = new Intl.DateTimeFormat(locale, { month: 'long' }); } catch { fmt = null; }
  return Array.from({ length: 12 }, (_, i) => {
    const value = String(i + 1).padStart(2, '0');
    const raw = fmt ? fmt.format(new Date(2000, i, 1)) : value;
    const label = raw.charAt(0).toUpperCase() + raw.slice(1);
    return { value, label };
  });
}

/** Years from next year back `span` years, plus `extra` (a stored year outside the
 * range) so an existing value is never silently dropped from the select. */
export function yearOptions(now: Date, span = 60, extra?: string): { value: string; label: string }[] {
  const start = now.getFullYear() + 1;
  const years: string[] = [];
  for (let y = start; y > start - span; y--) years.push(String(y));
  if (extra && /^\d{4}$/.test(extra) && !years.includes(extra)) {
    years.push(extra);
    years.sort((a, b) => Number(b) - Number(a));
  }
  return years.map((y) => ({ value: y, label: y }));
}
