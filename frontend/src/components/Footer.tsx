import React from 'react';
import { useI18n } from '../i18n';

export function Footer() {
  const { t } = useI18n();
  return (
  <footer className="fixed bottom-0 left-0 right-0 z-40 bg-white/90 dark:bg-neutral-900/90 backdrop-blur border-t border-neutral-200 dark:border-neutral-800 text-neutral-700 dark:text-neutral-300">
      <div className="max-w-5xl mx-auto px-4 py-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs sm:text-sm">
        <span className="whitespace-pre">{t('footer.brandline')}</span>
        <span className="hidden sm:inline">•</span>

        <a
          href="https://www.linkedin.com/in/ian-dalton-data"
          target="_blank"
          rel="noopener noreferrer"
          className="text-red-400 hover:text-red-300 underline-offset-2 hover:underline"
        >
          linkedin.com/in/ian-dalton-data
        </a>

        <span className="hidden sm:inline">•</span>
        <a
          href="https://link.mercadopago.com.ar/betterresume"
          target="_blank"
          rel="noopener noreferrer"
          className="btn-secondary btn-sm"
          aria-label={t('donate.cta')}
        >
          {t('donate.cta')}
        </a>
      </div>
    </footer>
  );
}
