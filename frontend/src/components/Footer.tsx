import React from 'react';
import { useI18n } from '../i18n';
import { useNavigate } from 'react-router-dom';


export function Footer({ geoLocation, onDonateClick }: { geoLocation: { isArgentina: boolean } | null; onDonateClick?: (show: boolean) => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  
  const setShowDonate = (show: boolean) => {
    onDonateClick?.(show);
  };

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
        
        <span className="hidden md:inline text-green-600 dark:text-green-400 font-medium">
          {t('footer.gotJob')}
        </span>

        {!geoLocation || !geoLocation.isArgentina ? (
              <button onClick={() => { navigate('/donate'); setShowDonate(false); }} className="btn-primary">{t('donate.cta')}</button>
            ) : (
              <a href="https://link.mercadopago.com.ar/betterresume" target="_blank" rel="noreferrer" className="btn-primary">{t('donate.cta')}</a>
            )}
      </div>
    </footer>
  );
}
