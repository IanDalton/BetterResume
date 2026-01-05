import React, { useEffect, useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import {
  EmbeddedCheckoutProvider,
  EmbeddedCheckout
} from '@stripe/react-stripe-js';
import { useSearchParams, Link } from 'react-router-dom';
import Confetti from 'react-confetti';
import { useI18n } from '../i18n';
import { authStateListener } from '../services/firebase';

// Initialize Stripe
const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLIC_KEY);

const API_BASE_RAW = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_BASE = API_BASE_RAW.replace(/\/+$/, '');

export function Donate() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const [clientSecret, setClientSecret] = useState<string | null>(searchParams.get('client_secret'));
  const [amount, setAmount] = useState(5);
  const [reason, setReason] = useState<'support' | 'job'>('support');
  const [userId, setUserId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showConfetti, setShowConfetti] = useState(false);

  useEffect(() => {
    const unsub = authStateListener(user => {
      if (user) {
        setUserId(user.uid);
      } else {
        const guestId = localStorage.getItem('br.guestId');
        setUserId(guestId);
      }
    });
    return () => unsub();
  }, []);

  // If client_secret is in URL, use it
  useEffect(() => {
    const secret = searchParams.get('client_secret');
    if (secret) {
      setClientSecret(secret);
    }
  }, [searchParams]);

  const handleDonateClick = async () => {
    if (!amount || amount < 1) {
      alert(t('donate.error.amount'));
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      // Call backend to create Stripe checkout session
      const response = await fetch(`${API_BASE}/create-donation-session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: Math.round(amount * 100), // Convert to cents
          currency: 'USD', // Defaulting to USD for now, can add currency selector if needed
          reason,
          user_id: userId
        }),
      });

      if (!response.ok) {
        throw new Error(`${t('donate.error.session')}: ${response.status}`);
      }

      const data = await response.json();
      const secret = data.clientSecret;

      if (!secret) {
        throw new Error(t('donate.error.secret'));
      }

      setClientSecret(secret);
      // Optionally update URL so refresh works
      setSearchParams({ client_secret: secret });
    } catch (err: any) {
      console.error('Donation error:', err);
      setError(err.message || t('donate.error.process'));
    } finally {
      setIsLoading(false);
    }
  };
const handleReasonChange = (newReason: 'support' | 'job') => {
    setReason(newReason);
    if (newReason === 'job') {
      setAmount(25);
      setShowConfetti(true);
    } else {
      setShowConfetti(false);
    }
  };

  
  if (clientSecret) {
    return (
      <div className="min-h-screen bg-neutral-50 dark:bg-neutral-900 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-neutral-900 dark:text-white">
              {t('donate.complete.title')}
            </h1>
            <Link to="/donate" onClick={() => { setClientSecret(null); setSearchParams({}); }} className="text-sm text-blue-600 hover:underline mt-2 inline-block">
              {t('donate.changeAmount')}
            </Link>
          </div>
          
          <div className="bg-white dark:bg-neutral-800 rounded-xl shadow-lg overflow-hidden">
            <EmbeddedCheckoutProvider
              stripe={stripePromise}
              options={{ clientSecret }}
            >
              <EmbeddedCheckout />
            </EmbeddedCheckoutProvider>
          </div>

          <div className="mt-8 text-center">
            <Link to="/" className="text-sm text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300">
      {showConfetti && <Confetti recycle={false} numberOfPieces={500} />}
              {t('donate.back')}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-neutral-50 dark:bg-neutral-900 py-12 px-4 sm:px-6 lg:px-8 flex items-center justify-center">
      {showConfetti && (
        <Confetti
          recycle={false}
          numberOfPieces={500}
          onConfettiComplete={() => setShowConfetti(false)}
        />
      )}
      <div className="max-w-md w-full space-y-8 bg-white dark:bg-neutral-800 p-8 rounded-xl shadow-lg">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-white">
            {t('donate.support.title')}
          </h1>
          <p className="mt-2 text-neutral-600 dark:text-neutral-400">
            {t('donate.support.subtitle')}
          </p>
        </div>

        <div className="space-y-6">
          
          <div className="mb-6">
            <label className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              {t('donate.reason.label')}
            </label>
            <div className="flex space-x-4">
              <button
                onClick={() => handleReasonChange('support')}
                className={`flex-1 py-3 px-4 rounded-lg border transition-colors ${
                  reason === 'support'
                    ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300'
                    : 'border-neutral-200 dark:border-neutral-700 hover:border-neutral-300 dark:hover:border-neutral-600 text-neutral-600 dark:text-neutral-400'
                }`}
              >
                {t('donate.reason.support')}
              </button>
              <button
                onClick={() => handleReasonChange('job')}
                className={`flex-1 py-3 px-4 rounded-lg border transition-colors ${
                  reason === 'job'
                    ? 'border-green-500 bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300'
                    : 'border-neutral-200 dark:border-neutral-700 hover:border-neutral-300 dark:hover:border-neutral-600 text-neutral-600 dark:text-neutral-400'
                }`}
              >
                {t('donate.reason.job')}
              </button>
            </div>
          </div>

          {reason === 'job' && (
            <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg border border-green-200 dark:border-green-800">
              <h3 className="text-lg font-semibold text-green-800 dark:text-green-300 mb-2">
                {t('donate.job.title')}
              </h3>
              <p className="text-sm text-green-700 dark:text-green-400 mb-3">
                {t('donate.job.subtitle')}
              </p>
            </div>
          )}

          <div>
            <label htmlFor="amount" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              {t('donate.amount.label')}
            </label>
            <div className="grid grid-cols-3 gap-3 mb-4">
              {[5, 10, 20].map((val) => (
                <button
                  key={val}
                  onClick={() => setAmount(val)}
                  className={`py-2 px-4 rounded-lg border ${
                    amount === val
                      ? 'bg-blue-50 border-blue-500 text-blue-700 dark:bg-blue-900/30 dark:border-blue-400 dark:text-blue-300'
                      : 'border-neutral-300 dark:border-neutral-600 hover:bg-neutral-50 dark:hover:bg-neutral-700'
                  }`}
                >
                  ${val}
                </button>
              ))}
            </div>
            <div className="relative rounded-md shadow-sm">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                <span className="text-neutral-900 dark:text-white sm:text-sm">$</span>
              </div>
              <input
                type="number"
                name="amount"
                id="amount"
                min="1"
                className="block w-full rounded-md border-neutral-300 pl-7 pr-12 focus:border-blue-500 focus:ring-blue-500 dark:bg-neutral-700 dark:border-neutral-600 dark:text-white sm:text-sm py-3 font-semibold text-neutral-900"
                placeholder="0.00"
                value={amount}
                onChange={(e) => setAmount(Number(e.target.value))}
              />
            </div>
          </div>

          {error && (
            <div className="text-red-600 text-sm text-center bg-red-50 dark:bg-red-900/20 p-3 rounded-lg">
              {error}
            </div>
          )}

          <button
            onClick={handleDonateClick}
            disabled={isLoading}
            className="w-full flex justify-center py-3 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? t('donate.processing') : `${t('donate.button')}${amount}`}
          </button>

          <div className="text-center">
            <Link to="/" className="text-sm text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300">
              {t('donate.later')}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
