import { SITE_KINDS, emptyProfile } from '../types';
import type { LanguageEntry, ProfileLink, ProfileLinkKind, ResumeEntry, UserProfile } from '../types';

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

// Loads and, if needed, one-time-splits legacy localStorage data (mixed
// personal-info/language rows inside br.entries) into the new dedicated
// br.profile/br.languages/br.entries keys. Cached at module scope so multiple
// callers (e.g. lazy useState initializers) don't each redo the same parse.
let _localData: { profile: UserProfile; languages: LanguageEntry[]; entries: ResumeEntry[] } | null = null;
export function loadLocalDataWithMigration() {
  if (_localData) return _localData;
  let profile: UserProfile = { ...emptyProfile };
  let languages: LanguageEntry[] = [];
  let entries: ResumeEntry[] = [];
  try {
    const rawEntries = JSON.parse(localStorage.getItem('br.entries') || '[]');
    if (hasLegacyEntries(rawEntries)) {
      const split = splitLegacyEntries(rawEntries);
      profile = { ...emptyProfile, ...split.profile };
      languages = split.languages;
      entries = split.entries;
      try {
        localStorage.setItem('br.profile', JSON.stringify(profile));
        localStorage.setItem('br.languages', JSON.stringify(languages));
        localStorage.setItem('br.entries', JSON.stringify(entries));
      } catch {}
    } else {
      entries = Array.isArray(rawEntries) ? rawEntries : [];
      try { const p = localStorage.getItem('br.profile'); if (p) profile = { ...emptyProfile, ...JSON.parse(p) }; } catch {}
      try { const l = localStorage.getItem('br.languages'); if (l) languages = JSON.parse(l); } catch {}
    }
  } catch {}
  _localData = { profile, languages, entries };
  return _localData;
}
