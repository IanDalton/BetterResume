import React, { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { authStateListener, emailPasswordSignIn, emailPasswordSignUp, logout, loadUserData, UserDataDoc, googleSignIn } from '../services/firebase';
import { v4 as uuidv4 } from 'uuid';

interface AuthGateProps {
  onResolved: (user: { mode: 'auth' | 'guest'; uid: string; email?: string }, data?: UserDataDoc | null) => void;
  forceOpenSignal?: number; // changing value forces modal to open (guest -> sign in upgrade)
}

// Simple auth + guest selection UI shown on first visit or until resolved.
export const AuthGate: React.FC<AuthGateProps> = ({ onResolved, forceOpenSignal }) => {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Start hidden; only show after we know we need user interaction
  const [show, setShow] = useState(false);
  const { t } = useI18n();

  useEffect(() => {
    const unsub = authStateListener(user => {
      if (user) {
        setShow(false);
        loadUserData(user.uid).then(data => {
          onResolved({ mode: 'auth', uid: user.uid, email: user.email || undefined }, data);
        }).catch(()=>{
          onResolved({ mode: 'auth', uid: user.uid, email: user.email || undefined });
        });
      } else {
        // No authenticated user: ensure we have (or create) a guest and do NOT show modal automatically.
        let gid = localStorage.getItem('br.guestId');
        if (!gid) {
          try { gid = uuidv4(); } catch { gid = 'guest-' + Date.now().toString(36); }
          try { localStorage.setItem('br.guestId', gid); } catch {}
        }
        onResolved({ mode: 'guest', uid: gid! });
      }
    });
    return () => unsub();
  }, []);

  // Force open when requested (e.g., guest wants to sign in). Remove guest id beforehand externally.
  useEffect(() => {
    if (forceOpenSignal) {
      // Only open if not already authenticated (modal would auto-close on auth anyway)
      setShow(prev => prev || true);
    }
  }, [forceOpenSignal]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setError(null); setLoading(true);
      if (mode === 'signup') await emailPasswordSignUp(email, password); else await emailPasswordSignIn(email, password);
      // auth listener will handle resolution
    } catch (err: any) {
      setError(err.message || 'Auth failed');
    } finally { setLoading(false); }
  };

  const handleGoogle = async () => {
    try {
      setError(null); setLoading(true);
      await googleSignIn(); // auth listener will resolve
    } catch (e:any) {
      setError(e.message || 'Google sign-in failed');
    } finally { setLoading(false); }
  };

  const continueGuest = () => {
    try {
      // Generate ID with uuid; fallback to crypto.randomUUID or timestamp
      let id: string;
  try { id = uuidv4(); }
  catch { id = (typeof crypto !== 'undefined' && (crypto as any).randomUUID ? (crypto as any).randomUUID() : 'guest-' + Date.now().toString(36)); }
  console.log('[AuthGate] continueGuest clicked, generated id', id);
  try { localStorage.setItem('br.guestId', id); } catch (e) { console.warn('[AuthGate] Failed to write guestId', e); }
  setShow(false); // hide modal immediately for UX
  onResolved({ mode: 'guest', uid: id });
    } catch (e:any) {
      setError('Guest sign-in failed');
    }
  };

  if (!show) return null;

  return (
    <div className="fixed inset-0 bg-black/40 dark:bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="w-full max-w-md bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-6 shadow-xl space-y-5">
        <h2 className="text-xl font-semibold tracking-tight">{t('auth.welcome')}</h2>
  <p className="text-sm text-neutral-600 dark:text-neutral-400">{t('auth.tagline')}</p>
        <form onSubmit={submit} className="space-y-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400">{t('auth.email')}</label>
            <input type="email" required value={email} onChange={e=>setEmail(e.target.value)} className="bg-white dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded px-3 py-2 text-sm" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase tracking-wide text-neutral-600 dark:text-neutral-400">{t('auth.password')}</label>
            <input type="password" required value={password} onChange={e=>setPassword(e.target.value)} className="bg-white dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded px-3 py-2 text-sm" />
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <div className="flex items-center justify-between text-xs text-neutral-400">
            <button type="button" onClick={()=>setMode(mode==='signin'?'signup':'signin')} className="btn-link-primary">{mode==='signin'? t('auth.needAccount'): t('auth.haveAccount')}</button>
            {/* Guest option hidden because user is already a guest by default */}
          </div>
          <button disabled={loading} className="w-full mt-2 btn-primary disabled:opacity-50">{mode==='signin'? t('auth.signIn'): t('auth.createAccount')}</button>
      <div className="relative my-2">
            <div className="flex items-center">
        <div className="flex-grow h-px bg-neutral-200 dark:bg-neutral-700" />
        <span className="mx-2 text-[10px] uppercase tracking-wide text-neutral-500">{t('auth.or')}</span>
        <div className="flex-grow h-px bg-neutral-200 dark:bg-neutral-700" />
            </div>
          </div>
          <button type="button" onClick={handleGoogle} disabled={loading} className="w-full bg-neutral-100 text-neutral-900 hover:bg-white disabled:opacity-50 rounded py-2 text-sm font-medium flex items-center justify-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 488 512" className="w-4 h-4" fill="currentColor"><path d="M488 261.8C488 403.3 391.1 504 248 504 110.8 504 0 393.2 0 256S110.8 8 248 8c66.8 0 123 24.5 166.3 64.9l-67.5 64.9C258.5 52.6 94.3 116.6 94.3 256c0 86.5 69.1 156.6 153.7 156.6 98.2 0 135-70.4 140.8-106.9H248v-85.3h236.1c2.3 12.7 3.9 24.9 3.9 41.4z"/></svg>
            <span>{loading ? t('auth.working') : t('auth.continueGoogle')}</span>
          </button>
        </form>
  <p className="text-[11px] text-neutral-600 dark:text-neutral-500 leading-relaxed">{t('auth.guest.notice')}</p>
      </div>
    </div>
  );
};

export const UserBar: React.FC<{user: {mode:'auth'|'guest'; uid:string; email?:string}; onLogout: ()=>void; onSignInRequest?: ()=>void}> = ({ user, onLogout, onSignInRequest }) => {
  const { t } = useI18n();
  return (
  <div className="flex items-center gap-3 text-xs bg-neutral-100 dark:bg-neutral-800 border border-neutral-300 dark:border-neutral-700 rounded px-3 py-1">
      {user.mode === 'auth' ? (
        <>
      <span className="text-neutral-700 dark:text-neutral-300">{user.email}</span>
          <button onClick={onLogout} className="text-red-400 hover:text-red-300">{t('auth.logout')}</button>
        </>
      ) : (
        <>
      <span className="text-neutral-600 dark:text-neutral-400">{t('auth.guest')}</span>
      <span className="font-mono text-[10px] text-neutral-500 truncate max-w-[120px]" title={user.uid}>{user.uid}</span>
          <button onClick={onSignInRequest || onLogout} className="btn-link-primary">{t('auth.signIn')}</button>
        </>
      )}
    </div>
  );
};
