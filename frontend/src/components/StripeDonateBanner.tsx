import React, { useState } from 'react';
import { useI18n } from '../i18n';

interface Props {
  open: boolean;
  onClose: () => void;
  isArgentina?: boolean;
}

export function StripeDonateBanner({ open, onClose, isArgentina = false }: Props) {
  const { t } = useI18n();
  const [isLoading, setIsLoading] = useState(false);

  if (!open) return null;

  const handleDonateClick = async () => {
    setIsLoading(true);
    try {
      // Call backend to create Stripe checkout session
      const response = await fetch('/api/create-donation-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: 500, // $5 USD or equivalent
          currency: isArgentina ? 'ARS' : 'USD',
        }),
      });

      if (!response.ok) {
        throw new Error(`Failed to create session: ${response.status}`);
      }

      const { clientSecret } = await response.json();

      if (!clientSecret) {
        throw new Error('No client secret received');
      }

      // Redirect to Stripe checkout
      window.location.href = `/donate-checkout?client_secret=${encodeURIComponent(clientSecret)}`;
    } catch (error) {
      console.error('Donation error:', error);
      alert(t('donate.error') || 'Failed to process donation. Please try again.');
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 max-w-sm animate-in slide-in-from-bottom-2">
      <div className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-xl p-4 text-sm text-neutral-800 dark:text-neutral-200">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 text-red-400 text-lg">❤️</div>
          <div className="flex-1">
            <div className="font-semibold mb-1">{t('donate.stripe.title') || 'Help Keep BetterResume Free'}</div>
            <p className="text-neutral-700 dark:text-neutral-300 leading-relaxed text-xs mb-3">
              {isArgentina
                ? t('donate.stripe.body.argentina') || 'Si te resultó útil, considera hacer una pequeña donación para mantener el proyecto en funcionamiento.'
                : t('donate.stripe.body.international') || 'If this tool saved you time, consider supporting development with a small donation.'}
            </p>
            <div className="mt-3 flex gap-2">
              <button
                onClick={handleDonateClick}
                disabled={isLoading}
                className="btn-primary btn-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isLoading ? t('working') || 'Processing...' : (t('donate.stripe.cta') || 'Donate $5')}
              </button>
              <button
                className="btn-secondary btn-sm"
                onClick={onClose}
                disabled={isLoading}
              >
                {t('donate.toast.dismiss') || 'Not now'}
              </button>
            </div>
          </div>
          <button
            className="text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300 text-xs flex-shrink-0"
            aria-label="Close"
            onClick={onClose}
            disabled={isLoading}
          >
            ✕
          </button>
        </div>
      </div>
    </div>
  );
}
