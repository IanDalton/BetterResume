import React, { useEffect, useState } from 'react';
import {
  EmbeddedCheckoutProvider,
  EmbeddedCheckout
} from '@stripe/react-stripe-js';
import { useSearchParams, Link } from 'react-router-dom';
import { useI18n } from '../i18n';
import { authStateListener } from '../services/firebase';
import { getStripe } from '../services/stripe';
import { API_BASE } from '../services/api';
import { Button, Input, useToast } from '../components/ui';

const AMOUNT_PRESETS = [5, 10, 20, 25];
const JOB_PRESET = 25;
const MIN_AMOUNT = 1;

export function Donate() {
  const { t } = useI18n();
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [clientSecret, setClientSecret] = useState<string | null>(searchParams.get('client_secret'));
  const [stripePromise, setStripePromise] = useState<Promise<any> | null>(null);
  // Kept as the raw field text so clearing the input is possible; `amount` is derived.
  const [amountText, setAmountText] = useState('5');
  const [reason, setReason] = useState<'support' | 'job'>('support');
  const [userId, setUserId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const amount = Number(amountText);
  const amountValid = Number.isFinite(amount) && amount >= MIN_AMOUNT;

  useEffect(() => {
    setStripePromise(getStripe());
  }, []);

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
    if (!amountValid) return;
    setIsLoading(true);
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

      if (!response.ok) throw new Error(`Donation session failed: ${response.status}`);

      const data = await response.json();
      const secret = data.clientSecret;
      if (!secret) throw new Error('No client secret returned');

      setClientSecret(secret);
      // Optionally update URL so refresh works
      setSearchParams({ client_secret: secret });
    } catch (err: any) {
      console.error('Donation error:', err);
      toast({ title: t('donate.error.process'), variant: 'error' });
    } finally {
      setIsLoading(false);
    }
  };
  const handleReasonChange = (newReason: 'support' | 'job') => {
    setReason(newReason);
    if (newReason === 'job') {
      setAmountText(String(JOB_PRESET));
    }
  };


  if (clientSecret) {
    return (
      <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-neutral-900 dark:text-white">
              {t('donate.complete.title')}
            </h1>
            <Link to="/donate" onClick={() => { setClientSecret(null); setSearchParams({}); }} className="btn-link-primary text-sm mt-2 inline-block">
              {t('donate.changeAmount')}
            </Link>
          </div>

          <div className="bg-white dark:bg-neutral-900 rounded-xl shadow-lg overflow-hidden">
            {stripePromise ? (
              <EmbeddedCheckoutProvider
                stripe={stripePromise}
                options={{ clientSecret }}
              >
                <EmbeddedCheckout />
              </EmbeddedCheckoutProvider>
            ) : (
              <div className="p-8 text-center text-neutral-500">
                {t('donate.loadingPayment')}
              </div>
            )}
          </div>

          <div className="mt-8 text-center">
            <Link to="/" className="text-sm text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300">
              {t('donate.back')}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950 py-12 px-4 sm:px-6 lg:px-8 flex items-center justify-center">
      <div className="max-w-md w-full space-y-8 bg-white dark:bg-neutral-900 p-8 rounded-xl shadow-lg">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-white">
            {t('donate.support.title')}
          </h1>
          <p className="mt-2 text-neutral-600 dark:text-neutral-400">
            {t('donate.support.subtitle')}
          </p>
        </div>

        <div className="space-y-6">
          <fieldset>
            <legend className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              {t('donate.reason.label')}
            </legend>
            <div className="grid grid-cols-2 gap-3">
              <Button variant="option" selected={reason === 'support'} onClick={() => handleReasonChange('support')}>
                {t('donate.reason.support')}
              </Button>
              <Button variant="option" selected={reason === 'job'} onClick={() => handleReasonChange('job')}>
                {t('donate.reason.job')}
              </Button>
            </div>
          </fieldset>

          {reason === 'job' && (
            <div className="bg-red-50 dark:bg-red-900/20 p-4 rounded-lg border border-red-200 dark:border-red-800">
              <h3 className="text-lg font-semibold text-red-800 dark:text-red-300 mb-1">
                {t('donate.job.title')}
              </h3>
              <p className="text-sm text-red-700 dark:text-red-300">
                {t('donate.job.subtitle')}
              </p>
            </div>
          )}

          <div>
            <label htmlFor="amount" className="block text-sm font-medium text-neutral-700 dark:text-neutral-300 mb-2">
              {t('donate.amount.label')}
            </label>
            <div className="grid grid-cols-4 gap-2 mb-3">
              {AMOUNT_PRESETS.map((val) => (
                <Button key={val} variant="option" selected={amount === val} onClick={() => setAmountText(String(val))}>
                  ${val}
                </Button>
              ))}
            </div>
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                <span className="text-neutral-900 dark:text-white text-sm">$</span>
              </div>
              <Input
                type="number"
                name="amount"
                id="amount"
                min={MIN_AMOUNT}
                step="1"
                inputMode="decimal"
                className="block w-full pl-7 pr-4 py-3 font-semibold"
                placeholder="0.00"
                value={amountText}
                invalid={!amountValid}
                onChange={(e) => setAmountText(e.target.value)}
              />
            </div>
            {!amountValid && (
              <p className="mt-1 text-xs text-red-600 dark:text-red-400" role="alert">{t('donate.amount.invalid')}</p>
            )}
          </div>

          <Button
            variant="primary"
            onClick={handleDonateClick}
            loading={isLoading}
            disabled={!amountValid}
            className="w-full"
          >
            {isLoading ? t('donate.processing') : `${t('donate.button')}${amountValid ? amount : ''}`}
          </Button>

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
