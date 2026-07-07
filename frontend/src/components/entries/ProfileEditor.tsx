import React from 'react';
import { EDUCATION_TYPES, EXPERIENCE_TYPES, LanguageEntry, ResumeEntry, UserProfile } from '../../types';
import { Stepper, Button } from '../ui';
import { PersonalInfoSection } from './PersonalInfoSection';
import { EducationSection } from './EducationSection';
import { ExperienceSection } from './ExperienceSection';
import { LanguagesSection } from './LanguagesSection';
import { ResumeImportDialog } from './ResumeImportDialog';
import { SaveStatusIndicator, SaveStatus } from './SaveStatusIndicator';
import { personalInfoSchema } from './validation';
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
  onboardingComplete: boolean;
  onOnboardingComplete: () => void;
  saveStatus: SaveStatus;
}

export const ProfileEditor: React.FC<ProfileEditorProps> = ({
  userId, profile, onProfileChange, languages, onLanguagesChange,
  entries, onAddEntry, onUpdateEntry, onRemoveEntry,
  onboardingComplete, onOnboardingComplete, saveStatus,
}) => {
  const { t } = useI18n();
  const personalComplete = personalInfoSchema.safeParse(profile).success;
  const educationComplete = entries.some((e) => EDUCATION_TYPES.includes(e.type));
  const experienceComplete = entries.some((e) => EXPERIENCE_TYPES.includes(e.type));
  const allRequiredComplete = personalComplete && educationComplete && experienceComplete;

  const steps = [
    { label: t('wizard.stage.personal') },
    { label: t('wizard.stage.education') },
    { label: t('wizard.stage.experience') },
    { label: t('wizard.stage.languages') },
  ];
  const completions = [personalComplete, educationComplete, experienceComplete, true];
  const firstIncomplete = completions.findIndex((c) => !c);
  const currentStep = firstIncomplete === -1 ? steps.length - 1 : firstIncomplete;
  const progressLabel = `${t('wizard.stepLabel')} ${currentStep + 1} ${t('wizard.of')} ${steps.length}: ${steps[currentStep].label}`;

  const incompleteMessage = !personalComplete ? t('validation.personal')
    : !educationComplete ? t('validation.education')
    : !experienceComplete ? t('validation.experience')
    : '';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {!onboardingComplete ? (
          <Stepper steps={steps} currentStep={currentStep} progressLabel={progressLabel} />
        ) : <span />}
        <div className="ml-auto flex items-center gap-3">
          <ResumeImportDialog
            userId={userId}
            currentProfile={profile}
            onProfileChange={onProfileChange}
            currentLanguages={languages}
            onLanguagesChange={onLanguagesChange}
            onAddEntry={onAddEntry}
          />
          <SaveStatusIndicator status={saveStatus} />
        </div>
      </div>
      <PersonalInfoSection profile={profile} onChange={onProfileChange} />
      <EducationSection entries={entries} onAdd={onAddEntry} onUpdate={onUpdateEntry} onRemove={onRemoveEntry} />
      <ExperienceSection entries={entries} onAdd={onAddEntry} onUpdate={onUpdateEntry} onRemove={onRemoveEntry} />
      <LanguagesSection languages={languages} onChange={onLanguagesChange} />
      {!onboardingComplete && (
        <div className="flex items-center justify-between gap-3 border-t border-neutral-200 pt-4 dark:border-neutral-800">
          <p className="text-xs text-neutral-500 dark:text-neutral-400">{incompleteMessage}</p>
          <Button variant="primary" disabled={!allRequiredComplete} onClick={onOnboardingComplete}>
            {t('wizard.finish')}
          </Button>
        </div>
      )}
    </div>
  );
};
