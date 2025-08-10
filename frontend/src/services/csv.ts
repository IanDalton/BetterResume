import type { ResumeEntry } from '../types';

export function buildCsvFromEntries(entries: ResumeEntry[]): string {
  const header = ['title','company','startDate','endDate','description'];
  const lines = [header.join(',')];
  for (const e of entries) {
    if (['job','contract','part-time','project','non-profit','education'].includes(e.type)) {
      const row = [
        e.role || '',
        e.company || '',
        e.start || '',
        e.end || '',
        (e.description || '') + (e.role_description ? `\n${e.role_description}` : '')
      ];
      lines.push(row.map(sanitize).join(','));
    }
  }
  return lines.join('\n');
}

function sanitize(v: string) {
  if (v == null) return '';
  if (v.includes(',') || v.includes('\n') || v.includes('"')) return '"' + v.replace(/"/g,'""') + '"';
  return v;
}
