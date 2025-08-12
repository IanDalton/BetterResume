// Lightweight GA4 wrapper with error/console tracking
declare global {
  interface Window {
    dataLayer: any[];
    gtag: (...args: any[]) => void;
  }
}

let enabled = false;
let MEASUREMENT_ID: string | undefined;

function loadGtag(id: string) {
  const src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(id)}`;
  if (document.querySelector(`script[src^="${src}"]`)) return;
  const s = document.createElement('script');
  s.async = true; s.src = src;
  document.head.appendChild(s);
}

export function initAnalytics(measurementId: string) {
  if (!measurementId || enabled) return;
  MEASUREMENT_ID = measurementId;
  loadGtag(measurementId);
  window.dataLayer = window.dataLayer || [];
  window.gtag = window.gtag || (function(){ (window as any).dataLayer.push(arguments as any); } as any);
  window.gtag('js', new Date());
  // Disable auto page_view; SPA will send manually
  window.gtag('config', measurementId, { anonymize_ip: true, send_page_view: false });
  enabled = true;
}

export function pageView(path: string, title?: string) {
  if (!enabled || !MEASUREMENT_ID) return;
  window.gtag('event', 'page_view', {
    page_location: window.location.href,
    page_path: path,
    page_title: title || document.title
  });
}

export function trackEvent(name: string, params?: Record<string, any>) {
  if (!enabled) return;
  try { window.gtag('event', name, params || {}); } catch { /* no-op */ }
}

export function setupErrorTracking() {
  if (!enabled) return;
  window.addEventListener('error', (e) => {
    trackEvent('exception', {
      description: (e as any).message,
      fatal: true,
      file: (e as any).filename,
      lineno: (e as any).lineno,
      colno: (e as any).colno,
    });
  });
  window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
    const reason: any = (e && (e as any).reason);
    const message = reason?.message || String(reason || 'unhandledrejection');
    trackEvent('exception', { description: message, fatal: false });
  });
}

export function trackConsole(maxPerMinute = 10) {
  if (!enabled) return;
  const origError = console.error.bind(console);
  const origWarn = console.warn.bind(console);
  let start = Date.now();
  let count = 0;
  function allow() {
    const now = Date.now();
    if (now - start > 60_000) { start = now; count = 0; }
    if (count < maxPerMinute) { count++; return true; }
    return false;
  }
  console.error = (...args: any[]) => {
    if (allow()) trackEvent('console_error', { msg: String(args[0] || ''), extra: args.length>1 ? '1' : '0' });
    return origError(...args);
  };
  console.warn = (...args: any[]) => {
    if (allow()) trackEvent('console_warn', { msg: String(args[0] || ''), extra: args.length>1 ? '1' : '0' });
    return origWarn(...args);
  };
}
