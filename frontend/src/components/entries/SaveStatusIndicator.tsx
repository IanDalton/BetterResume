import React from 'react';
import { Spinner, cn } from '../ui';
import { useI18n } from '../../i18n';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export const SaveStatusIndicator: React.FC<{ status: SaveStatus }> = ({ status }) => {
  const { t } = useI18n();
  if (status === 'idle') return null;
  const label = status === 'saving' ? t('save.status.saving')
    : status === 'saved' ? t('save.status.saved')
    : t('save.status.error');
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs',
        status === 'error' ? 'text-red-500' : 'text-neutral-500 dark:text-neutral-400'
      )}
    >
      {status === 'saving' && <Spinner size="xs" />}
      {label}
    </span>
  );
};
