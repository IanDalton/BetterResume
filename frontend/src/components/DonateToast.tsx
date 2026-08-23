import React from 'react';
import { useI18n } from '../i18n';
import { Button } from './ui';

interface Props {
  open: boolean;
  onClose: () => void;
  onDonateClick?: () => void; // callback when donate button clicked
  href?: string; // donation link
}

export function DonateToast({ open, onClose, onDonateClick, href }: Props) {
  const { t } = useI18n();
  if (!open) return null;
  const link = href || 'https://link.mercadopago.com.ar/betterresume';
  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-sm">
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-xl p-4 text-sm text-neutral-800 dark:text-neutral-200">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 text-red-400">❤</div>
          <div className="flex-1">
            <div className="font-semibold mb-1">{t('donate.toast.title')}</div>
            <p className="text-neutral-700 dark:text-neutral-300 leading-relaxed">
              {t('donate.toast.body')}
            </p>
            <div className="mt-3 flex gap-2">
              {onDonateClick ? (
                <Button
                  size="sm"
                  onClick={() => {
                    onDonateClick();
                    onClose();
                  }}
                >
                  {t('donate.toast.cta')}
                </Button>
              ) : (
                <Button asChild size="sm">
                  <a
                    href={link}
                    target="_blank"
                    rel="noreferrer"
                    onClick={() => {
                      onClose();
                    }}
                  >
                    {t('donate.toast.cta')}
                  </a>
                </Button>
              )}
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  onClose();
                }}
              >
                {t('donate.toast.dismiss')}
              </Button>
            </div>
          </div>
          <button
            className="text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 text-xs"
            aria-label={t('donate.toast.close')}
            onClick={() => {
              onClose();
            }}
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  );
}
