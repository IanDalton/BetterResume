import React from 'react';
import { cn } from './cn';
import { useI18n } from '../../i18n';

export type SpinnerSize = 'xs' | 'sm' | 'md' | 'lg';

const sizeClass: Record<SpinnerSize, string> = {
  xs: 'h-3 w-3 border-2',
  sm: 'h-4 w-4 border-2',
  md: 'h-6 w-6 border-2',
  lg: 'h-10 w-10 border-[3px]',
};

export const Spinner: React.FC<{ size?: SpinnerSize; className?: string }> = ({ size = 'md', className }) => {
  const { t } = useI18n();
  return (
    <span
      role="status"
      aria-label={t('aria.loading')}
      className={cn(
        'inline-block animate-spin rounded-full border-current border-t-transparent align-[-2px]',
        sizeClass[size],
        className
      )}
    />
  );
};
