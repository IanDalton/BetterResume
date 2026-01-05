import React from 'react';
import { Link } from 'react-router-dom';
import Confetti from 'react-confetti';
import { useI18n } from '../i18n';

export function ThankYou() {
  const { t } = useI18n();
  return (
    <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100">
      <Confetti width={window.innerWidth} height={window.innerHeight} />
      <div className="text-center p-8 max-w-md">
        <div className="mb-6 text-6xl">🎉</div>
        <h1 className="text-3xl font-bold mb-4">{t('thankyou.title')}</h1>
        <p className="text-lg text-neutral-600 dark:text-neutral-400 mb-8">
          {t('thankyou.message')}
        </p>
        <Link 
          to="/" 
          className="inline-block px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors"
        >
          {t('thankyou.back')}
        </Link>
      </div>
    </div>
  );
}
