import type { ResumeEntry } from '../types';

export function buildCsvFromEntries(entries: ResumeEntry[]): string {
  // Match reference jobs.csv header exactly
  const header = ['type','company','location','role','start_date','end_date','description'];
  const lines = [header.join(',')];
  const norm = (val?: string) => {
    if (!val) return '';
    const v = String(val).trim();
    if (!v) return '';
    const low = v.toLowerCase();
    if (['present','current','now'].includes(low)) return 'present';
    // Accept MM/YYYY or M/YYYY -> 01/MM/YYYY
    let m = v.match(/^(\d{1,2})\/(\d{4})$/);
    if (m) {
      const mm = m[1].padStart(2,'0');
      return `01/${mm}/${m[2]}`;
    }
    // Accept YYYY/MM or YYYY-M -> 01/MM/YYYY
    m = v.match(/^(\d{4})[\/-](\d{1,2})$/);
    if (m) {
      const mm = m[2].padStart(2,'0');
      return `01/${mm}/${m[1]}`;
    }
    // Accept DD/MM/YYYY type; pad components if needed
    m = v.match(/^(\d{1,2})[\/-](\d{1,2})[\/-](\d{4})$/);
    if (m) {
      const dd = m[1].padStart(2,'0');
      const mm = m[2].padStart(2,'0');
      return `${dd}/${mm}/${m[3]}`;
    }
    return v; // leave as-is; backend will keep string if not parseable
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
