import React from 'react';
import { Link } from 'react-router-dom';
import { useI18n } from '../i18n';
import { ThemeToggle } from './ThemeToggle';
import { MERCADOPAGO_URL } from '../services/config';

/** Plain page footer: brand line, author link, a discreet donate link and the theme
 * toggle. It flows with the page instead of floating over it. */
export function Footer({ geoLocation }: { geoLocation: { isArgentina: boolean } | null }) {
  const { t } = useI18n();
  const linkClass = 'btn-link-primary';

  return (
    <footer className="mt-16 border-t border-neutral-200 pb-8 pt-6 text-sm text-neutral-600 dark:border-neutral-800 dark:text-neutral-400">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span>{t('footer.brandline')}</span>
        <span aria-hidden>·</span>
        <a href="https://www.linkedin.com/in/ian-dalton-data" target="_blank" rel="noopener noreferrer" className={linkClass}>
          LinkedIn
        </a>
        <span aria-hidden>·</span>
        {geoLocation?.isArgentina ? (
          <a href={MERCADOPAGO_URL} target="_blank" rel="noreferrer" className={linkClass}>{t('donate.cta')}</a>
        ) : (
          <Link to="/donate" className={linkClass}>{t('donate.cta')}</Link>
        )}
        <span className="ml-auto">
          <ThemeToggle />
        </span>
      </div>
    </footer>
  );
}
