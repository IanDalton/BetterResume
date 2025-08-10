export type EntryType = 'info' | 'education' | 'job' | 'non-profit' | 'project' | 'contract' | 'part-time';

export interface ResumeEntry {
  type: EntryType;
  company?: string;
  location?: string;
  role: string;
  start?: string;
  end?: string;
  description?: string;
  role_description?: string;
}

export const isWorkLike = (t: EntryType) => ['job','contract','part-time','project','non-profit','education'].includes(t);
