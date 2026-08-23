import { useCallback, useEffect, useState } from 'react';

const DAY_MS = 24 * 60 * 60 * 1000;
// Show the one-time "please donate" modal once the user has generated this many resumes.
const MODAL_MILESTONE_GENERATIONS = 5;
// Small delay before nudging so it never appears mid-interaction.
const NUDGE_DELAY_MS = 1500;

const STORAGE_KEYS = {
  toastLastShownAt: 'br.donateNudge.lastShownAt',
  modalShown: 'br.donateNudge.modalShown',
} as const;

interface UseDonationNudgesOptions {
  /** Successful resume-generation count, used for the one-time modal milestone. */
  resumeCount: number;
  /** Suppress nudges while something else is already asking for the user's attention
   * (generation modal, first-load guide, etc). */
  busy: boolean;
}

interface UseDonationNudgesResult {
  showToast: boolean;
  /** Call when the toast is dismissed (closed, donate clicked, or ignored) — records the
   * cooldown so the next nudge waits a full day. */
  dismissToast: () => void;
  showModal: boolean;
  /** Call when the modal is dismissed — the modal only ever shows once. */
  dismissModal: () => void;
}

/**
 * Single source of truth for "should we ask this user to donate right now".
 *
 * Replaces four independent, uncoordinated mechanisms that used to live inline in
 * Home.tsx (a passive daily toast, a Stripe-specific count/day toast, a generation-count
 * toast, and a one-time milestone modal — each with its own localStorage key and magic
 * number) with one hook, one cooldown, and a clear priority: the one-time modal wins over
 * the daily toast, and only one nudge is ever eligible to show at a time.
 */
export function useDonationNudges({ resumeCount, busy }: UseDonationNudgesOptions): UseDonationNudgesResult {
  const [showToast, setShowToast] = useState(false);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    if (busy || showToast || showModal) return;

    const id = setTimeout(() => {
      let modalAlreadyShown = false;
      try { modalAlreadyShown = localStorage.getItem(STORAGE_KEYS.modalShown) === '1'; } catch { /* ignore */ }

      if (!modalAlreadyShown && resumeCount >= MODAL_MILESTONE_GENERATIONS) {
        setShowModal(true);
        return;
      }

      let lastShownAt = 0;
      try { lastShownAt = Number.parseInt(localStorage.getItem(STORAGE_KEYS.toastLastShownAt) || '0', 10); } catch { /* ignore */ }
      const cooldownElapsed = Date.now() - lastShownAt > DAY_MS;
      if (cooldownElapsed) {
        setShowToast(true);
      }
    }, NUDGE_DELAY_MS);

    return () => clearTimeout(id);
  }, [resumeCount, busy, showToast, showModal]);

  const dismissToast = useCallback(() => {
    try { localStorage.setItem(STORAGE_KEYS.toastLastShownAt, String(Date.now())); } catch { /* ignore */ }
    setShowToast(false);
  }, []);

  const dismissModal = useCallback(() => {
    try { localStorage.setItem(STORAGE_KEYS.modalShown, '1'); } catch { /* ignore */ }
    setShowModal(false);
  }, []);

  return { showToast, dismissToast, showModal, dismissModal };
}
