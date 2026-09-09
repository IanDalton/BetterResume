import React from 'react';
import { LanguageEntry, ResumeEntry, UserProfile } from '../../types';
import { PersonalInfoSection } from './PersonalInfoSection';
import { EducationSection } from './EducationSection';
import { ExperienceSection } from './ExperienceSection';
import { LanguagesSection } from './LanguagesSection';
import { ResumeImportDialog } from './ResumeImportDialog';
import { SaveStatusIndicator, SaveStatus } from './SaveStatusIndicator';
import { useI18n } from '../../i18n';

export interface ProfileEditorProps {
  userId: string;
  profile: UserProfile;
  onProfileChange: (p: UserProfile) => void;
  languages: LanguageEntry[];
  onLanguagesChange: (l: LanguageEntry[]) => void;
  entries: ResumeEntry[];
  onAddEntry: (e: ResumeEntry) => void;
  onUpdateEntry: (i: number, e: ResumeEntry) => void;
  onRemoveEntry: (i: number) => void;
  saveStatus: SaveStatus;
  /** Extra cards rendered after the built-in sections (e.g. the profile photo card). */
  children?: React.ReactNode;
}

/**
 * The profile block: import action, then one card per section. Each card carries its
 * own completion badge, which is all the progress signal the page needs.
 */
export const ProfileEditor: React.FC<ProfileEditorProps> = ({
  userId, profile, onProfileChange, languages, onLanguagesChange,
  entries, onAddEntry, onUpdateEntry, onRemoveEntry, saveStatus, children,
}) => {
  const { t } = useI18n();
  const isEmpty = !profile.fullName && !profile.email && entries.length === 0 && languages.length === 0;

  const importDialog = (
    <ResumeImportDialog
      userId={userId}
      currentProfile={profile}
      onProfileChange={onProfileChange}
      currentLanguages={languages}
      onLanguagesChange={onLanguagesChange}
      onAddEntry={onAddEntry}
      primary={isEmpty}
    />
  );

  return (
    <div className="space-y-4">
      {isEmpty ? (
        <div className="flex flex-col gap-3 rounded-xl border border-dashed border-neutral-300 bg-neutral-50 p-5 dark:border-neutral-700 dark:bg-neutral-900/60 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-neutral-700 dark:text-neutral-300">{t('resume.import.emptyState')}</p>
          <div className="shrink-0">{importDialog}</div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-end gap-3">
          <SaveStatusIndicator status={saveStatus} />
          {importDialog}
        </div>
      )}
      <PersonalInfoSection profile={profile} onChange={onProfileChange} />
      <ExperienceSection entries={entries} onAdd={onAddEntry} onUpdate={onUpdateEntry} onRemove={onRemoveEntry} />
      <EducationSection entries={entries} onAdd={onAddEntry} onUpdate={onUpdateEntry} onRemove={onRemoveEntry} />
      <LanguagesSection languages={languages} onChange={onLanguagesChange} />
      {children}
    </div>
  );
};
