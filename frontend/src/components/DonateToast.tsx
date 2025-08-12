import React from 'react';
import { useI18n } from '../i18n';

interface Props {
  open: boolean;
  onClose: () => void;
  href?: string; // donation link
}

export function DonateToast({ open, onClose, href }: Props) {
  const { t } = useI18n();
  if (!open) return null;
  const link = href || 'https://link.mercadopago.com.ar/betterresume';
  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-sm">
      <div className="rounded-lg border border-neutral-700 bg-neutral-900 shadow-xl p-4 text-sm text-neutral-200">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 text-red-400">❤</div>
          <div className="flex-1">
            <div className="font-semibold mb-1">{t('donate.toast.title')}</div>
            <p className="text-neutral-300 leading-relaxed">
              {t('donate.toast.body')}
            </p>
            <div className="mt-3 flex gap-2">
              <a
                href={link}
                target="_blank"
                rel="noreferrer"
                className="btn-primary btn-sm"
                onClick={() => {
                  onClose();
                }}
              >
                {t('donate.toast.cta')}
              </a>
              <button
                className="btn-secondary btn-sm"
                onClick={() => {
                  onClose();
                }}
              >
                {t('donate.toast.dismiss')}
              </button>
            </div>
          </div>
          <button
            className="text-neutral-500 hover:text-neutral-300 text-xs"
            aria-label="Close"
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
