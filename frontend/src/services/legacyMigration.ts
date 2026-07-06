import type { LanguageEntry, ProfileLink, ProfileLinkKind, ResumeEntry, UserProfile } from '../types';

const SITE_KINDS: ProfileLinkKind[] = ['portfolio', 'github', 'linkedin', 'twitter', 'blog', 'other'];

/**
 * Splits a legacy mixed `entries` array (the old encoding, where personal info
 * lived as type='info' rows with `company` as the field key and `description`
 * as the value, and languages lived as type='language' rows) into the new
 * split shape. Mirrors backend/utils/legacy_migration.py's decode functions
 * exactly, so client-side data (localStorage, Firestore) migrates the same
 * way the backend's one-time DB backfill does.
 *
 * Safe to call on already-migrated data: entries with a type not in the old
 * 'info'/'language' set pass through unchanged into `entries`.
 */
export function splitLegacyEntries(raw: any[]): { profile: Partial<UserProfile>; languages: LanguageEntry[]; entries: ResumeEntry[] } {
  const profile: Partial<UserProfile> = {};
  const links: ProfileLink[] = [];
  const languages: LanguageEntry[] = [];
  const entries: ResumeEntry[] = [];

  for (const e of raw || []) {
    if (!e || typeof e !== 'object') continue;
    if (e.type === 'info') {
      const key = String(e.company || '').trim().toLowerCase();
      const desc = String(e.description || '');
      if (key === 'name') profile.fullName = desc;
      else if (key === 'email') profile.email = desc;
      else if (key === 'phone') profile.phone = desc;
      else if (key === 'address') profile.address = desc;
      else if (key === 'website') {
        const [url, label] = desc.split('\n', 2);
        if (url && url.trim()) {
          const trimmedLabel = (label || '').trim();
          if ((SITE_KINDS as string[]).includes(trimmedLabel)) {
            links.push({ kind: trimmedLabel as ProfileLinkKind, label: null, url: url.trim() });
          } else if (trimmedLabel) {
            links.push({ kind: 'other', label: trimmedLabel, url: url.trim() });
          } else {
            links.push({ kind: 'other', label: null, url: url.trim() });
          }
        }
      }
      // Unrecognized 'info' keys are dropped -- same as the backend backfill.
    } else if (e.type === 'language') {
      const name = String(e.role || e.company || '').trim();
      if (name) languages.push({ name, proficiency: String(e.description || '').trim() });
    } else {
      entries.push(e as ResumeEntry);
    }
  }

  if (links.length) profile.links = links;
  return { profile, languages, entries };
}

/** True if `raw` contains any legacy type='info'/'language' rows needing a split. */
export function hasLegacyEntries(raw: any[]): boolean {
  return Array.isArray(raw) && raw.some(e => e && (e.type === 'info' || e.type === 'language'));
}
