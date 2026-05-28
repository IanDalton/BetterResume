import { loadStripe, Stripe } from '@stripe/stripe-js';
import { API_BASE } from './api';

let stripePromise: Promise<Stripe | null> | null = null;

export const getStripe = async (): Promise<Stripe | null> => {
  if (stripePromise) return stripePromise;

  // Try env var first (build-time)
  const envKey = import.meta.env.VITE_STRIPE_PUBLIC_KEY;
  if (envKey) {
    stripePromise = loadStripe(envKey);
    return stripePromise;
  }

  // Fetch from backend (runtime)
  try {
    const res = await fetch(`${API_BASE}/stripe-config`);
    if (res.ok) {
      const { publicKey } = await res.json();
      if (publicKey) {
        stripePromise = loadStripe(publicKey);
        return stripePromise;
      }
    }
  } catch (e) {
    console.error('Failed to load Stripe config', e);
  }

  return null;
};
