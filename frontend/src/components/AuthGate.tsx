import React, { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { authStateListener, emailPasswordSignIn, emailPasswordSignUp, loadUserData, UserDataDoc, googleSignIn, resetPassword } from '../services/firebase';
import { v4 as uuidv4 } from 'uuid';
import { Dialog, FormField, Input, Button } from './ui';
import { useToast } from './ui/use-toast';

/** Maps a Firebase Auth error code to a translated, user-facing message. Firebase's own
 * `err.message` is English-only, technical, and inconsistent with the rest of this form's
 * i18n — this keeps the common cases in the app's own voice and falls back to a generic
 * translated message for anything unmapped rather than showing the raw SDK string. */
function authErrorMessage(err: any, t: (key: string) => string, fallbackKey: string): string {
  const code: string | undefined = err?.code;
  switch (code) {
    case 'auth/invalid-credential':
    case 'auth/invalid-login-credentials':
      return t('auth.error.invalidCredential');
    case 'auth/user-not-found':
      return t('auth.error.userNotFound');
    case 'auth/wrong-password':
      return t('auth.error.wrongPassword');
    case 'auth/email-already-in-use':
      return t('auth.error.emailInUse');
    case 'auth/weak-password':
      return t('auth.error.weakPassword');
    case 'auth/invalid-email':
      return t('auth.error.invalidEmail');
    case 'auth/too-many-requests':
      return t('auth.error.tooManyRequests');
    default:
      return t(fallbackKey);
  }
}

/** The guest id is the key the backend stores the profile photo under, so it must survive
 * reloads: reuse the stored one and only mint a new id when there is none. Home.tsx
 * seeds its initial state with the same rule. */
export function getOrCreateGuestId(): string {
  let gid: string | null = null;
  try { gid = localStorage.getItem('br.guestId'); } catch { gid = null; }
  if (gid) return gid;
  try { gid = uuidv4(); } catch { gid = 'guest-' + Date.now().toString(36); }
  try { localStorage.setItem('br.guestId', gid); } catch { /* ignore */ }
  return gid;
}

interface AuthGateProps {
  onResolved: (user: { mode: 'auth' | 'guest'; uid: string; email?: string }, data?: UserDataDoc | null) => void;
  forceOpenSignal?: number; // changing value forces modal to open (guest -> sign in upgrade)
}

// Sign-in dialog. Nobody is forced through it: without an account the app simply runs
// as a guest, and the dialog only opens when the user asks to sign in.
export const AuthGate: React.FC<AuthGateProps> = ({ onResolved, forceOpenSignal }) => {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Start hidden; only show after we know we need user interaction
  const [show, setShow] = useState(false);
  const [resetting, setResetting] = useState(false);
  const { t } = useI18n();
  const { toast } = useToast();

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
        onResolved({ mode: 'guest', uid: getOrCreateGuestId() });
      }
    });
    return () => unsub();
  }, []);

  // Force open when requested (e.g., guest wants to sign in).
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
      setError(authErrorMessage(err, t, 'auth.error.generic'));
    } finally { setLoading(false); }
  };

  const handleGoogle = async () => {
    try {
      setError(null); setLoading(true);
      await googleSignIn(); // auth listener will resolve
    } catch (e:any) {
      setError(authErrorMessage(e, t, 'auth.error.google'));
    } finally { setLoading(false); }
  };

  const handleForgotPassword = async () => {
    if (!email.trim()) {
      setError(t('auth.resetPassword.needEmail'));
      return;
    }
    try {
      setError(null); setResetting(true);
      await resetPassword(email.trim());
      toast({ title: t('auth.resetPassword.sent'), variant: 'success' });
    } catch (err: any) {
      setError(authErrorMessage(err, t, 'auth.resetPassword.error'));
    } finally { setResetting(false); }
  };

  return (
    <Dialog
      open={show}
      onOpenChange={setShow}
      title={t('auth.welcome')}
      description={t('auth.tagline')}
    >
      <form onSubmit={submit} className="space-y-4">
        <FormField label={t('auth.email')} required>
          <Input type="email" required autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} />
        </FormField>
        <FormField label={t('auth.password')} required>
          <Input type="password" required autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} value={password} onChange={e => setPassword(e.target.value)} />
        </FormField>
        {error && <p className="text-sm text-red-600 dark:text-red-400" role="alert">{error}</p>}
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <Button type="button" variant="link" size="sm" onClick={()=>{ setError(null); setMode(mode==='signin'?'signup':'signin'); }}>
            {mode==='signin'? t('auth.needAccount'): t('auth.haveAccount')}
          </Button>
          {mode === 'signin' && (
            <Button type="button" variant="link" size="sm" onClick={handleForgotPassword} disabled={resetting}>
              {resetting ? t('auth.working') : t('auth.forgotPassword')}
            </Button>
          )}
        </div>
        <Button type="submit" variant="primary" loading={loading} className="w-full mt-2">
          {mode==='signin'? t('auth.signIn'): t('auth.createAccount')}
        </Button>
        <div className="relative my-2">
          <div className="flex items-center">
            <div className="flex-grow h-px bg-neutral-200 dark:bg-neutral-700" />
            <span className="mx-2 text-xs text-neutral-500">{t('auth.or')}</span>
            <div className="flex-grow h-px bg-neutral-200 dark:bg-neutral-700" />
          </div>
        </div>
        <Button type="button" variant="secondary" onClick={handleGoogle} disabled={loading} className="w-full">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 488 512" className="w-4 h-4 mr-2" fill="currentColor" aria-hidden><path d="M488 261.8C488 403.3 391.1 504 248 504 110.8 504 0 393.2 0 256S110.8 8 248 8c66.8 0 123 24.5 166.3 64.9l-67.5 64.9C258.5 52.6 94.3 116.6 94.3 256c0 86.5 69.1 156.6 153.7 156.6 98.2 0 135-70.4 140.8-106.9H248v-85.3h236.1c2.3 12.7 3.9 24.9 3.9 41.4z"/></svg>
          <span>{loading ? t('auth.working') : t('auth.continueGoogle')}</span>
        </Button>
      </form>
      <p className="mt-4 text-xs leading-relaxed text-neutral-600 dark:text-neutral-400">{t('auth.guest.notice')}</p>
    </Dialog>
  );
};

export const UserBar: React.FC<{user: {mode:'auth'|'guest'; uid:string; email?:string}; onLogout: ()=>void; onSignInRequest?: ()=>void}> = ({ user, onLogout, onSignInRequest }) => {
  const { t } = useI18n();
  return (
    <div className="flex min-h-[40px] items-center gap-2 rounded-lg border border-neutral-300 bg-neutral-100 px-3 text-sm dark:border-neutral-700 dark:bg-neutral-800">
      {user.mode === 'auth' ? (
        <>
          <span className="max-w-[12rem] truncate text-neutral-700 dark:text-neutral-300" title={user.email}>{user.email}</span>
          <span aria-hidden className="text-neutral-400">·</span>
          <Button type="button" variant="link" size="sm" onClick={onLogout}>{t('auth.logout')}</Button>
        </>
      ) : (
        <>
          <span className="text-neutral-600 dark:text-neutral-400">{t('auth.guest')}</span>
          <span aria-hidden className="text-neutral-400">·</span>
          <Button type="button" variant="link" size="sm" onClick={onSignInRequest || onLogout}>{t('auth.signIn')}</Button>
        </>
      )}
    </div>
  );
};
