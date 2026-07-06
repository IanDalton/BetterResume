import React from 'react';
import { useI18n } from '../i18n';
import { Dialog, Button } from './ui';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function FirstLoadGuide({ open, onClose }: Props) {
  const { t } = useI18n();
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && onClose()}
      title={t('guide.title')}
      description={t('app.tagline')}
      footer={
        <Button variant="primary" size="sm" onClick={onClose}>
          {t('guide.gotIt')}
        </Button>
      }
    >
      <div className="space-y-3 text-sm leading-relaxed">
        <p className="text-neutral-700 dark:text-neutral-300">{t('guide.intro')}</p>
        <ol className="list-decimal pl-5 space-y-2">
          <li>{t('guide.step1')}</li>
          <li>{t('guide.step2')}</li>
          <li>{t('guide.step3')}</li>
          <li>{t('guide.step4')}</li>
        </ol>
        <p className="text-xs text-neutral-600 dark:text-neutral-500">{t('guide.tip')}</p>
      </div>
    </Dialog>
  );
}
