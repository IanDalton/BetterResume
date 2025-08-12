import React from 'react';
import { useI18n } from '../i18n';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function FirstLoadGuide({ open, onClose }: Props) {
  const { t } = useI18n();
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 dark:bg-black/70 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-6 shadow-2xl space-y-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">{t('guide.title')}</h2>
            <p className="text-sm text-neutral-600 dark:text-neutral-400 mt-1">{t('app.tagline')}</p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-neutral-500 hover:text-neutral-300 text-sm">✕</button>
        </div>

        <div className="space-y-3 text-sm leading-relaxed">
          <p className="text-neutral-300">{t('guide.intro')}</p>
          <ol className="list-decimal pl-5 space-y-2">
            <li>{t('guide.step1')}</li>
            <li>{t('guide.step2')}</li>
            <li>{t('guide.step3')}</li>
            <li>{t('guide.step4')}</li>
          </ol>
          <p className="text-xs text-neutral-600 dark:text-neutral-500">{t('guide.tip')}</p>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <button onClick={onClose} className="btn-primary btn-sm">{t('guide.gotIt')}</button>
        </div>
      </div>
    </div>
  );
}
