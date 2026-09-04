import React, { useMemo, useState } from 'react';
import { ProfileLink, ProfileLinkKind, SITE_KINDS, UserProfile } from '../../types';
import { FormField, Input, Select, Button } from '../ui';
import { SectionStatusBadge } from './SectionStatusBadge';
import { issuesToFieldErrors, personalInfoSchema } from './validation';
import { useI18n } from '../../i18n';

interface Props {
  profile: UserProfile;
  onChange: (p: UserProfile) => void;
}

export const PersonalInfoSection: React.FC<Props> = ({ profile, onChange }) => {
  const { t } = useI18n();
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const siteKindOptions = useMemo(
    () => SITE_KINDS.map((k) => ({ value: k, label: t(`site.${k}`) })),
    [t]
  );
  const schema = useMemo(() => personalInfoSchema(t), [t]);

  const result = schema.safeParse(profile);
  const errors: Record<string, string> = result.success ? {} : issuesToFieldErrors(result.error.issues);
  const isComplete = !errors.fullName && !errors.email;
  const markTouched = (k: string) => setTouched((t) => ({ ...t, [k]: true }));
  const setField = (k: keyof UserProfile, v: string) => onChange({ ...profile, [k]: v } as UserProfile);

  const [newUrl, setNewUrl] = useState('');
  const [newKind, setNewKind] = useState<ProfileLinkKind>('linkedin');
  const [newLabel, setNewLabel] = useState('');
  const [newUrlError, setNewUrlError] = useState<string | undefined>(undefined);

  const isValidUrl = (raw: string) => {
    // The URL constructor is too lenient to catch typos on its own — e.g. "https://not a
    // url" parses successfully as host "not%20a%20url" instead of throwing — so also
    // reject whitespace and require a real-looking hostname (has a dot, isn't just ".").
    if (/\s/.test(raw)) return false;
    const candidate = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
    try {
      const url = new URL(candidate);
      return url.hostname.includes('.') && !url.hostname.startsWith('.') && !url.hostname.endsWith('.');
    } catch {
      return false;
    }
  };

  const addLink = () => {
    const trimmed = newUrl.trim();
    if (!trimmed) return;
    if (!isValidUrl(trimmed)) {
      setNewUrlError(t('personal.links.url.invalid'));
      return;
    }
    setNewUrlError(undefined);
    const link: ProfileLink = { kind: newKind, label: newKind === 'other' ? newLabel.trim() || null : null, url: trimmed };
    onChange({ ...profile, links: [...profile.links, link] });
    setNewUrl('');
    setNewLabel('');
  };
  const removeLink = (i: number) => onChange({ ...profile, links: profile.links.filter((_, idx) => idx !== i) });
  const updateLink = (i: number, patch: Partial<ProfileLink>) =>
    onChange({ ...profile, links: profile.links.map((l, idx) => (idx === i ? { ...l, ...patch } : l)) });

  return (
    <div className="rounded-xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-2 text-base font-semibold text-neutral-900 dark:text-neutral-100">
          {t('section.personal.title')}
          <SectionStatusBadge complete={isComplete} required />
        </h3>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label={t('personal.fullName')} required error={touched.fullName ? errors.fullName : undefined}>
          <Input
            value={profile.fullName}
            autoComplete="name"
            onBlur={() => markTouched('fullName')}
            onChange={(e) => setField('fullName', e.target.value)}
            invalid={touched.fullName && !!errors.fullName}
          />
        </FormField>
        <FormField label={t('personal.email')} required error={touched.email ? errors.email : undefined}>
          <Input
            type="email"
            autoComplete="email"
            value={profile.email}
            onBlur={() => markTouched('email')}
            onChange={(e) => setField('email', e.target.value)}
            invalid={touched.email && !!errors.email}
          />
        </FormField>
        <FormField label={t('personal.phone')}>
          <Input value={profile.phone || ''} autoComplete="tel" onChange={(e) => setField('phone', e.target.value)} />
        </FormField>
        <FormField label={t('personal.address')}>
          <Input value={profile.address || ''} onChange={(e) => setField('address', e.target.value)} />
        </FormField>
      </div>
      <div className="mt-5 space-y-3">
        <p className="text-sm font-medium text-neutral-700 dark:text-neutral-300">{t('personal.links')}</p>
        <div className="flex flex-col gap-2 rounded-lg border border-dashed border-neutral-300 p-2 dark:border-neutral-700 sm:flex-row sm:items-start">
          <Select
            options={siteKindOptions}
            value={newKind}
            aria-label={t('personal.links.siteName')}
            onValueChange={(v) => setNewKind(v as ProfileLinkKind)}
            className="sm:w-40"
          />
          {newKind === 'other' && (
            <Input className="sm:w-36" placeholder={t('personal.links.siteName')} aria-label={t('personal.links.siteName')} value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
          )}
          <div className="flex-1">
            <Input
              className="w-full"
              placeholder="https://..."
              aria-label="URL"
              value={newUrl}
              invalid={!!newUrlError}
              onChange={(e) => { setNewUrl(e.target.value); if (newUrlError) setNewUrlError(undefined); }}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addLink(); } }}
            />
            {newUrlError && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{newUrlError}</p>}
          </div>
          <Button type="button" variant="secondary" onClick={addLink}>{t('personal.links.add')}</Button>
        </div>
        {profile.links.length > 0 && (
          <ul className="space-y-2" aria-label={t('personal.links')}>
            {profile.links.map((link, i) => (
              <li
                key={i}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 p-2 dark:border-neutral-800 dark:bg-neutral-800/50"
              >
                <Select
                  options={siteKindOptions}
                  value={link.kind}
                  aria-label={t('personal.links.siteName')}
                  onValueChange={(v) => updateLink(i, { kind: v as ProfileLinkKind })}
                  className="w-36"
                />
                {link.kind === 'other' && (
                  <Input
                    className="w-36"
                    placeholder={t('personal.links.siteName')}
                    aria-label={t('personal.links.siteName')}
                    value={link.label || ''}
                    onChange={(e) => updateLink(i, { label: e.target.value })}
                  />
                )}
                <Input
                  className="min-w-[10rem] flex-1"
                  aria-label="URL"
                  value={link.url}
                  onChange={(e) => updateLink(i, { url: e.target.value })}
                />
                <Button variant="tertiary" size="xs" onClick={() => removeLink(i)}>{t('personal.links.remove')}</Button>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('personal.links.help')}</p>
      </div>
    </div>
  );
};
