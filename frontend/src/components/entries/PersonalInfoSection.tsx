import React, { useState } from 'react';
import { ProfileLink, ProfileLinkKind, SITE_KINDS, UserProfile } from '../../types';
import { FormField, Input, Select, Button, cn } from '../ui';
import { personalInfoSchema } from './validation';
import { useI18n } from '../../i18n';

interface Props {
  profile: UserProfile;
  onChange: (p: UserProfile) => void;
}

export const PersonalInfoSection: React.FC<Props> = ({ profile, onChange }) => {
  const { t } = useI18n();
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const siteKindOptions = SITE_KINDS.map((k) => ({ value: k, label: k }));

  const result = personalInfoSchema.safeParse(profile);
  const errors: Record<string, string> = {};
  if (!result.success) {
    for (const issue of result.error.issues) {
      const key = issue.path[0];
      if (typeof key === 'string') errors[key] = issue.message;
    }
  }
  const isComplete = !errors.fullName && !errors.email;
  const markTouched = (k: string) => setTouched((t) => ({ ...t, [k]: true }));
  const setField = (k: keyof UserProfile, v: string) => onChange({ ...profile, [k]: v } as UserProfile);

  const [newUrl, setNewUrl] = useState('');
  const [newKind, setNewKind] = useState<ProfileLinkKind>('linkedin');
  const [newLabel, setNewLabel] = useState('');

  const addLink = () => {
    if (!newUrl.trim()) return;
    const link: ProfileLink = { kind: newKind, label: newKind === 'other' ? newLabel.trim() || null : null, url: newUrl.trim() };
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
        <h3 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">{t('section.personal.title')}</h3>
        <span
          className={cn(
            'rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide',
            isComplete
              ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
          )}
        >
          {isComplete ? t('section.complete') : t('section.required')}
        </span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label={t('wizard.personal.fullName')} required error={touched.fullName ? errors.fullName : undefined}>
          <Input
            value={profile.fullName}
            onBlur={() => markTouched('fullName')}
            onChange={(e) => setField('fullName', e.target.value)}
            invalid={touched.fullName && !!errors.fullName}
          />
        </FormField>
        <FormField label={t('wizard.personal.email')} required error={touched.email ? errors.email : undefined}>
          <Input
            type="email"
            value={profile.email}
            onBlur={() => markTouched('email')}
            onChange={(e) => setField('email', e.target.value)}
            invalid={touched.email && !!errors.email}
          />
        </FormField>
        <FormField label={t('wizard.personal.phone')}>
          <Input value={profile.phone || ''} onChange={(e) => setField('phone', e.target.value)} />
        </FormField>
        <FormField label={t('wizard.personal.address')}>
          <Input value={profile.address || ''} onChange={(e) => setField('address', e.target.value)} />
        </FormField>
      </div>
      <div className="mt-5 space-y-3">
        <label className="block text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400">
          {t('wizard.personal.websites')}
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Select options={siteKindOptions} value={newKind} onValueChange={(v) => setNewKind(v as ProfileLinkKind)} className="sm:w-40" />
          {newKind === 'other' && (
            <Input className="sm:w-32" placeholder={t('wizard.personal.label')} value={newLabel} onChange={(e) => setNewLabel(e.target.value)} />
          )}
          <Input
            className="flex-1"
            placeholder="https://..."
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addLink(); } }}
          />
          <Button type="button" variant="secondary" onClick={addLink}>{t('wizard.personal.add')}</Button>
        </div>
        {profile.links.length > 0 && (
          <ul className="space-y-2">
            {profile.links.map((link, i) => (
              <li
                key={i}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 p-2 dark:border-neutral-800 dark:bg-neutral-800/50"
              >
                <Select
                  options={siteKindOptions}
                  value={link.kind}
                  onValueChange={(v) => updateLink(i, { kind: v as ProfileLinkKind })}
                  className="w-36"
                />
                {link.kind === 'other' && (
                  <Input
                    className="w-32"
                    placeholder={t('wizard.personal.label')}
                    value={link.label || ''}
                    onChange={(e) => updateLink(i, { label: e.target.value })}
                  />
                )}
                <Input
                  className="min-w-[10rem] flex-1"
                  value={link.url}
                  onChange={(e) => updateLink(i, { url: e.target.value })}
                />
                <Button variant="danger" size="xs" onClick={() => removeLink(i)}>{t('wizard.personal.remove')}</Button>
              </li>
            ))}
          </ul>
        )}
        <p className="text-[11px] text-neutral-500 dark:text-neutral-500">{t('wizard.personal.help')}</p>
      </div>
    </div>
  );
};
