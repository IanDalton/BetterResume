import React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cn } from './cn';
import { Spinner } from './Spinner';

/**
 * - `primary`: the one main action on a surface (filled brand red).
 * - `secondary` / `tertiary`: supporting actions.
 * - `link`: inline text action (edit, sign in, ...).
 * - `danger`: destructive confirmation only (outlined red, never filled) — meant for
 *   ConfirmDialog, not for per-row delete buttons.
 * - `option`: a selectable choice (use `selected` to mark the current one).
 */
export type ButtonVariant = 'primary' | 'secondary' | 'tertiary' | 'link' | 'danger' | 'option';
export type ButtonSize = 'xs' | 'sm' | 'md';

const variantClass: Record<ButtonVariant, string> = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  tertiary: 'btn-tertiary',
  link: 'btn-link-primary',
  danger: 'btn-danger',
  option: 'btn-option',
};

const sizeClass: Record<ButtonSize, string> = {
  xs: 'btn-xs',
  sm: 'btn-sm',
  md: '',
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  asChild?: boolean;
  /** For `variant="option"`: marks this choice as the selected one. */
  selected?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', loading, asChild, selected, className, disabled, children, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    const selectable = variant === 'option';
    return (
      <Comp
        ref={ref}
        className={cn(variantClass[variant], sizeClass[size], className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        aria-pressed={selectable ? !!selected : undefined}
        data-selected={selectable ? String(!!selected) : undefined}
        {...props}
      >
        {asChild ? (
          // Radix Slot requires exactly one child element to clone onto — passing the
          // loading-spinner fragment alongside `children` (even when `loading` is falsy)
          // makes it two children and Slot throws. asChild callers own a single element
          // (e.g. <a>/<Link>) anyway, so there's nowhere to inject a sibling spinner.
          children
        ) : (
          <>
            {loading && <Spinner size="xs" className="mr-2" />}
            {children}
          </>
        )}
      </Comp>
    );
  }
);
Button.displayName = 'Button';
