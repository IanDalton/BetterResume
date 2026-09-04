import React from 'react';
import { cn } from '../ui';
import { useI18n } from '../../i18n';

interface Props {
  complete: boolean;
  /** Only sections that block generation show a "missing" badge while incomplete. */
  required?: boolean;
}

/** Completion badge next to a profile section title. Optional sections show nothing
 * until they have content, so the page never claims something is required when it isn't. */
export const SectionStatusBadge: React.FC<Props> = ({ complete, required }) => {
  const { t } = useI18n();
  if (!complete && !required) return null;
  return (
    <span
      className={cn(
        'rounded-full px-2 py-0.5 text-xs font-medium',
        complete
          ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
          : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
      )}
    >
      {complete ? t('section.complete') : t('section.required')}
    </span>
  );
};
