import { describe, expect, it } from 'vitest';
import { MODAL_MILESTONE_GENERATIONS, decideDonationNudge } from '../useDonationNudges';

const DAY_MS = 24 * 60 * 60 * 1000;
const NOW = 1_800_000_000_000;

describe('decideDonationNudge', () => {
  it('never nudges a visitor who has not generated a resume yet', () => {
    expect(decideDonationNudge({ resumeCount: 0, modalAlreadyShown: false, toastLastShownAt: 0, now: NOW })).toBeNull();
  });

  it('shows the toast after the first resume when the cooldown has elapsed', () => {
    expect(decideDonationNudge({ resumeCount: 1, modalAlreadyShown: false, toastLastShownAt: 0, now: NOW })).toBe('toast');
    expect(decideDonationNudge({ resumeCount: 1, modalAlreadyShown: false, toastLastShownAt: NOW - DAY_MS - 1, now: NOW })).toBe('toast');
  });

  it('respects the daily cooldown', () => {
    expect(decideDonationNudge({ resumeCount: 3, modalAlreadyShown: false, toastLastShownAt: NOW - DAY_MS / 2, now: NOW })).toBeNull();
  });

  it('prefers the one-time milestone modal over the toast', () => {
    expect(decideDonationNudge({ resumeCount: MODAL_MILESTONE_GENERATIONS, modalAlreadyShown: false, toastLastShownAt: 0, now: NOW })).toBe('modal');
    expect(decideDonationNudge({ resumeCount: MODAL_MILESTONE_GENERATIONS, modalAlreadyShown: true, toastLastShownAt: 0, now: NOW })).toBe('toast');
  });
});
