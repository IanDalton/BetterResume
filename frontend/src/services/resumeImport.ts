import type { ResumeImportEntry } from './api';
import type { EntryType, ResumeEntry } from '../types';

/** Maps a parsed resume-import entry (backend JobRecord-ish shape,
 * start_date/end_date) onto the frontend's ResumeEntry shape (start/end). */
export function importedEntryToResumeEntry(e: ResumeImportEntry): ResumeEntry {
  return {
    type: e.type as EntryType,
    company: e.company || '',
    location: e.location || '',
    role: e.role || '',
    start: e.start_date || '',
    end: e.end_date || '',
    description: e.description || '',
  };
}
