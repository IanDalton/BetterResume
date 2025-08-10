import type { ResumeEntry } from '../types';

export function buildCsvFromEntries(entries: ResumeEntry[]): string {
  // Match reference jobs.csv header exactly
  const header = ['type','company','location','role','start_date','end_date','description'];
  const lines = [header.join(',')];
  const norm = (v?: string) => {
    if (!v) return '';
    const m = v.match(/^(\d{1,2})\/(\d{4})$/); // MM/YYYY
    if (m) {
      const mm = m[1].padStart(2,'0');
      return `01/${mm}/${m[2]}`; // add day for consistency
    }
    return v; // assume already dd/mm/YYYY or another acceptable form
  };
  for (const e of entries) {
    if (e.type === 'info') {
      // company column becomes the key (name/email/etc), description column stores value
      lines.push([
        e.type,
        e.role || '',
        '',
        '',
        '',
        '',
        (e.description || '') + (e.role_description ? `\n${e.role_description}` : '')
      ].map(sanitize).join(','));
    } else if (['job','contract','part-time','project','non-profit','education','certification'].includes(e.type)) {
      lines.push([
        e.type,
        e.company || '',
        e.location || '',
        e.role || '',
        norm(e.start),
        norm(e.end),
        (e.description || '') + (e.role_description ? `\n${e.role_description}` : '')
      ].map(sanitize).join(','));
    }
  }
  return lines.join('\n');
}

function sanitize(v: string) {
  if (v == null) return '';
  if (v.includes(',') || v.includes('\n') || v.includes('"')) return '"' + v.replace(/"/g,'""') + '"';
  return v;
}
