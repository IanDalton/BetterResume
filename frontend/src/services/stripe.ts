import { loadStripe, Stripe } from '@stripe/stripe-js';

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
    const API_BASE_RAW = import.meta.env.VITE_API_URL || 'http://localhost:8000/resume';
    const API_BASE = API_BASE_RAW.replace(/\/+$/, '');
    
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
