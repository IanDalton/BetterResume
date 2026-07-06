export type EntryType = 'education' | 'certification' | 'job' | 'non-profit' | 'project' | 'contract' | 'part-time';

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

// Entry types grouped by which section of the entry-management UI they belong to.
export const EDUCATION_TYPES: EntryType[] = ['education', 'certification'];
export const EXPERIENCE_TYPES: EntryType[] = ['job', 'contract', 'part-time', 'project', 'non-profit'];

export type ProfileLinkKind = 'portfolio' | 'github' | 'linkedin' | 'twitter' | 'blog' | 'other';

export interface ProfileLink {
  kind: ProfileLinkKind;
  label?: string | null;
  url: string;
}

export interface UserProfile {
  fullName: string;
  email: string;
  phone?: string;
  address?: string;
  links: ProfileLink[];
}

export const emptyProfile: UserProfile = { fullName: '', email: '', phone: '', address: '', links: [] };

export interface LanguageEntry {
  name: string;
  proficiency: string;
}
