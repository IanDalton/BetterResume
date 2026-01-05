import React, { useEffect, useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import {
  EmbeddedCheckoutProvider,
  EmbeddedCheckout
} from '@stripe/react-stripe-js';
import { getStripe } from '../services/stripe';

export function DonateCheckout() {
  const [clientSecret, setClientSecret] = useState<string | null>(null);
  const [stripePromise, setStripePromise] = useState<Promise<any> | null>(null);

  useEffect(() => {
    setStripePromise(getStripe());
  }, []);

  useEffect(() => {
    // Get client_secret from URL search params
    const query = new URLSearchParams(window.location.search);
    const secret = query.get('client_secret');
    if (secret) {
      setClientSecret(secret);
    }
  }, []);

  if (!clientSecret) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100">

        <div className="text-center p-8">
          <h2 className="text-xl font-semibold mb-2">Missing Payment Information</h2>
          <p className="text-neutral-600 dark:text-neutral-400 mb-4">
            We couldn't find the payment session details. Please try again.
          </p>
          <a href="/" className="text-blue-600 hover:underline">Return Home</a>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-neutral-50 dark:bg-neutral-900 py-12 px-4 sm:px-6 lg:px-8">

      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-white">
            Support BetterResume
          </h1>
          <p className="mt-2 text-neutral-600 dark:text-neutral-400">
            Your donation helps keep this tool free and running.
          </p>
        </div>
        
        <div className="bg-white dark:bg-neutral-800 rounded-xl shadow-lg overflow-hidden">
          {stripePromise && clientSecret ? (
            <EmbeddedCheckoutProvider
              stripe={stripePromise}
              options={{ clientSecret }}
            >
              <EmbeddedCheckout />
            </EmbeddedCheckoutProvider>
          ) : (
            <div className="p-8 text-center text-neutral-500">
              Loading payment...
            </div>
          )}
        </div>

        <div className="mt-8 text-center">
          <a href="/" className="text-sm text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300">
            ← Back to BetterResume
          </a>
        </div>
      </div>
    </div>
  );
}
