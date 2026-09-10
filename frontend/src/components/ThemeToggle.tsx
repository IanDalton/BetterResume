import React from 'react';
import { Button } from './ui';
import { useI18n } from '../i18n';

type Theme = 'light' | 'dark' | 'system';

function prefersDark(): boolean {
  try { return !!window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches; } catch { return false; }
}

function resolve(theme: Theme): 'light' | 'dark' {
  return theme === 'system' ? (prefersDark() ? 'dark' : 'light') : theme;
}

/**
 * One labeled button that flips between light and dark. The app follows the system
 * until the user picks one; the choice is stored under `theme` (same key index.html
 * reads before first paint, so there is no flash on reload).
 */
export function ThemeToggle() {
  const { t } = useI18n();
  const [theme, setTheme] = React.useState<Theme>(() => {
    try {
      const saved = localStorage.getItem('theme') as Theme | null;
      return saved === 'light' || saved === 'dark' ? saved : 'system';
    } catch { return 'system'; }
  });
  const effective = resolve(theme);

  React.useEffect(() => {
    document.documentElement.classList.toggle('dark', effective === 'dark');
    try { localStorage.setItem('theme', theme); } catch {}
  }, [theme, effective]);

  React.useEffect(() => {
    if (theme !== 'system') return;
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => document.documentElement.classList.toggle('dark', mql.matches);
    mql.addEventListener?.('change', handler);
    return () => mql.removeEventListener?.('change', handler);
  }, [theme]);

  const next = effective === 'dark' ? 'light' : 'dark';
  return (
    <Button type="button" variant="tertiary" size="sm" onClick={() => setTheme(next)} aria-pressed={effective === 'dark'}>
      {next === 'dark' ? t('theme.toDark') : t('theme.toLight')}
    </Button>
  );
}
