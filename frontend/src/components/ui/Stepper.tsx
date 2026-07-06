import React from 'react';
import { cn } from './cn';

export interface StepperStep {
  label: string;
}

export interface StepperProps {
  steps: StepperStep[];
  currentStep: number;
  onStepClick?: (index: number) => void;
  /** Pre-translated "Step X of Y: Label" text. Defaults to an English string if omitted. */
  progressLabel?: string;
}

export const Stepper: React.FC<StepperProps> = ({ steps, currentStep, onStepClick, progressLabel }) => (
  <div>
    <p className="mb-2 text-xs font-medium text-neutral-500 dark:text-neutral-400">
      {progressLabel ?? `Step ${currentStep + 1} of ${steps.length}: ${steps[currentStep]?.label ?? ''}`}
    </p>
    <ol className="flex items-center gap-2" aria-label="Progress">
      {steps.map((step, i) => {
        const isCurrent = i === currentStep;
        const isDone = i < currentStep;
        const clickable = onStepClick && i <= currentStep;
        return (
          <li key={step.label} className="flex flex-1 items-center gap-2">
            <button
              type="button"
              disabled={!clickable}
              onClick={() => clickable && onStepClick?.(i)}
              className={cn(
                'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors',
                isCurrent && 'bg-red-600 text-white',
                isDone && !isCurrent && 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
                !isCurrent && !isDone && 'bg-neutral-200 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400',
                clickable && 'cursor-pointer hover:opacity-80',
                !clickable && 'cursor-default'
              )}
              aria-current={isCurrent ? 'step' : undefined}
            >
              {i + 1}
            </button>
            <span
              className={cn(
                'hidden text-xs font-medium sm:inline',
                isCurrent ? 'text-neutral-900 dark:text-neutral-100' : 'text-neutral-500 dark:text-neutral-400'
              )}
            >
              {step.label}
            </span>
            {i < steps.length - 1 && <span className="h-px flex-1 bg-neutral-200 dark:bg-neutral-800" />}
          </li>
        );
      })}
    </ol>
  </div>
);
