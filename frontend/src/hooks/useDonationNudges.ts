import { useCallback, useEffect, useState } from 'react';

const DAY_MS = 24 * 60 * 60 * 1000;
// Show the one-time "please donate" modal once the user has generated this many resumes.
export const MODAL_MILESTONE_GENERATIONS = 5;
// Never ask before the tool has delivered at least one resume.
export const TOAST_MIN_GENERATIONS = 1;
// Small delay before nudging so it never appears mid-interaction.
const NUDGE_DELAY_MS = 1500;

const STORAGE_KEYS = {
  toastLastShownAt: 'br.donateNudge.lastShownAt',
  modalShown: 'br.donateNudge.modalShown',
} as const;

export type DonationNudge = 'modal' | 'toast' | null;

export interface NudgeDecisionInput {
  resumeCount: number;
  modalAlreadyShown: boolean;
  /** Epoch ms of the last toast, 0 if never. */
  toastLastShownAt: number;
  now: number;
}

/**
 * Pure decision: which nudge (if any) is eligible right now. The one-time modal wins
 * over the daily toast; the toast requires at least one generated resume plus the
 * cooldown, so a first-time visitor is never asked for money before getting value.
 */
export function decideDonationNudge({ resumeCount, modalAlreadyShown, toastLastShownAt, now }: NudgeDecisionInput): DonationNudge {
  if (!modalAlreadyShown && resumeCount >= MODAL_MILESTONE_GENERATIONS) return 'modal';
  if (resumeCount < TOAST_MIN_GENERATIONS) return null;
  if (now - toastLastShownAt > DAY_MS) return 'toast';
  return null;
}

interface UseDonationNudgesOptions {
  /** Successful resume-generation count, used for the one-time modal milestone. */
  resumeCount: number;
  /** Suppress nudges while something else is already asking for the user's attention
   * (generation modal, etc). */
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
      let toastLastShownAt = 0;
      try { toastLastShownAt = Number.parseInt(localStorage.getItem(STORAGE_KEYS.toastLastShownAt) || '0', 10) || 0; } catch { /* ignore */ }

      const decision = decideDonationNudge({ resumeCount, modalAlreadyShown, toastLastShownAt, now: Date.now() });
      if (decision === 'modal') setShowModal(true);
      else if (decision === 'toast') setShowToast(true);
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
