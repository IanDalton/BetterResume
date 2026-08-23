import React from 'react';
import { Button } from './ui';
import { useI18n } from '../i18n';

type Theme = 'light' | 'dark' | 'system';

export function ThemeToggle({ onThemeChange }: { onThemeChange?: (theme: Theme) => void }) {
  const { t } = useI18n();
  const [theme, setTheme] = React.useState<Theme>(() => {
    try {
      const saved = localStorage.getItem('theme') as Theme | null;
      return saved || 'system';
    } catch { return 'system'; }
  });

  const applyTheme = React.useCallback((next: Theme) => {
    const root = document.documentElement;
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const enableDark = next === 'dark' || (next === 'system' && prefersDark);
    root.classList.toggle('dark', enableDark);
    onThemeChange?.(next);
  }, [onThemeChange]);

  React.useEffect(() => {
    applyTheme(theme);
    try { localStorage.setItem('theme', theme); } catch {}
  }, [theme, applyTheme]);

  React.useEffect(() => {
    if (theme !== 'system') return;
    const mql = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => applyTheme('system');
    mql.addEventListener?.('change', handler);
    return () => mql.removeEventListener?.('change', handler);
  }, [theme, applyTheme]);

  return (
    <div className="flex items-center gap-1">
      <Button type="button" variant="secondary" size="sm" title={t('theme.light')} aria-label={t('theme.light')} onClick={() => setTheme('light')} className={`px-2 ${theme==='light' ? 'ring-2 ring-red-500' : ''}`}>☀️</Button>
      <Button type="button" variant="secondary" size="sm" title={t('theme.dark')} aria-label={t('theme.dark')} onClick={() => setTheme('dark')} className={`px-2 ${theme==='dark' ? 'ring-2 ring-red-500' : ''}`}>🌙</Button>
      <Button type="button" variant="secondary" size="sm" title={t('theme.system')} aria-label={t('theme.system')} onClick={() => setTheme('system')} className={`px-2 ${theme==='system' ? 'ring-2 ring-red-500' : ''}`}>🖥️</Button>
    </div>
  );
}
