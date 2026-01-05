import React, { useState } from 'react';
import { useI18n } from '../i18n';
const API_BASE_RAW = import.meta.env.VITE_API_URL || 'http://localhost:8000/resume';
const API_BASE = API_BASE_RAW.replace(/\/+$/, '');

interface Props {
  open: boolean;
  onClose: () => void;
  isArgentina?: boolean;
}

export function StripeDonateBanner({ open, onClose, isArgentina = false }: Props) {
  const { t } = useI18n();
  const [isLoading, setIsLoading] = useState(false);
  const [amount, setAmount] = useState(isArgentina ? 1000 : 5);

  if (!open) return null;

  const handleDonateClick = async () => {
    if (!amount || amount < 1) {
      alert("Please enter a valid amount");
      return;
    }
    setIsLoading(true);
    try {
      // Call backend to create Stripe checkout session
      const response = await fetch(`${API_BASE}/create-donation-session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: Math.round(amount * 100), // Convert to cents/centavos
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
            
            <div className="flex items-center gap-2 mb-3">
              <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">
                Amount ({isArgentina ? 'ARS' : 'USD'}):
              </label>
              <div className="relative flex-1">
                <span className="absolute left-2 top-1/2 -translate-y-1/2 text-neutral-500">$</span>
                <input
                  type="number"
                  min="1"
                  value={amount}
                  onChange={(e) => setAmount(Number(e.target.value))}
                  className="w-full pl-6 pr-2 py-1 text-sm border border-neutral-300 dark:border-neutral-600 rounded bg-white dark:bg-neutral-800 focus:ring-2 focus:ring-blue-500 outline-none"
                />
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleDonateClick}
                disabled={isLoading || !amount}
                className="btn-primary btn-sm disabled:opacity-50 disabled:cursor-not-allowed flex-1"
              >
                {isLoading ? t('working') || 'Processing...' : `${t('donate.stripe.cta') || 'Donate'} $${amount}`}
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
