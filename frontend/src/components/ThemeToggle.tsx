import React from 'react';

type Theme = 'light' | 'dark' | 'system';

export function ThemeToggle({ onThemeChange }: { onThemeChange?: (theme: Theme) => void }) {
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
      <button type="button" title="Light" aria-label="Light theme" onClick={() => setTheme('light')} className={`btn-secondary btn-sm px-2 ${theme==='light' ? 'ring-2 ring-red-500' : ''}`}>☀️</button>
      <button type="button" title="Dark" aria-label="Dark theme" onClick={() => setTheme('dark')} className={`btn-secondary btn-sm px-2 ${theme==='dark' ? 'ring-2 ring-red-500' : ''}`}>🌙</button>
      <button type="button" title="System" aria-label="System theme" onClick={() => setTheme('system')} className={`btn-secondary btn-sm px-2 ${theme==='system' ? 'ring-2 ring-red-500' : ''}`}>🖥️</button>
    </div>
  );
}
