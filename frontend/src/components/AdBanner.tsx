import React from 'react';

type Props = {
  lightSrc: string;
  darkSrc: string;
  alt?: string;
  href?: string;
  className?: string;
};

export function AdBanner({ lightSrc, darkSrc, alt = 'Ad', href, className = '' }: Props) {
  const [isDark, setIsDark] = React.useState<boolean>(() => {
    try {
      if (typeof document !== 'undefined' && document.documentElement.classList.contains('dark')) return true;
      if (typeof window !== 'undefined' && window.matchMedia) {
        return window.matchMedia('(prefers-color-scheme: dark)').matches;
      }
    } catch {}
    return false;
  });
  React.useEffect(() => {
    try {
      const mql = window.matchMedia('(prefers-color-scheme: dark)');
      const handler = (e: MediaQueryListEvent) => setIsDark(e.matches || document.documentElement.classList.contains('dark'));
      if (mql && mql.addEventListener) mql.addEventListener('change', handler);
      else if ((mql as any).addListener) (mql as any).addListener(handler);
      return () => {
        if (mql && mql.removeEventListener) mql.removeEventListener('change', handler);
        else if ((mql as any).removeListener) (mql as any).removeListener(handler);
      };
    } catch {}
  }, []);

  const content = (
    <div className={`w-full overflow-hidden rounded border border-neutral-800 bg-neutral-900 ${className}`}>
      <img src={isDark ? darkSrc : lightSrc} alt={alt} className="w-full h-auto" />
    </div>
  );
  if (href) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" aria-label={alt} className="block">
        {content}
      </a>
    );
  }
  return content;
}
