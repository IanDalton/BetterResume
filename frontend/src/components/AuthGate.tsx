import React, { useEffect, useState } from 'react';
import { authStateListener, emailPasswordSignIn, emailPasswordSignUp, logout } from '../services/firebase';
import { v4 as uuidv4 } from 'uuid';

interface AuthGateProps {
  onResolved: (user: { mode: 'auth' | 'guest'; uid: string; email?: string }) => void;
}

// Simple auth + guest selection UI shown on first visit or until resolved.
export const AuthGate: React.FC<AuthGateProps> = ({ onResolved }) => {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [show, setShow] = useState(true);

  useEffect(() => {
    const unsub = authStateListener(user => {
      if (user) {
        setShow(false);
        onResolved({ mode: 'auth', uid: user.uid, email: user.email || undefined });
      }
    });
    // If guest already chosen previously
    const existingGuest = localStorage.getItem('br.guestId');
    if (existingGuest) {
      setShow(false);
      onResolved({ mode: 'guest', uid: existingGuest });
    }
    return () => unsub();
  }, [onResolved]);

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

  const continueGuest = () => {
    if (!confirm('Continuing as guest means your data is only saved in this browser and may be lost. Continue?')) return;
    const id = uuidv4();
    localStorage.setItem('br.guestId', id);
    setShow(false);
    onResolved({ mode: 'guest', uid: id });
  };

  if (!show) return null;

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="w-full max-w-md bg-neutral-900 border border-neutral-700 rounded-xl p-6 shadow-xl space-y-5">
        <h2 className="text-xl font-semibold tracking-tight">Welcome</h2>
        <p className="text-sm text-neutral-400">Create an account to save your resumes across devices. Or continue as a guest (local only).</p>
        <form onSubmit={submit} className="space-y-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase tracking-wide text-neutral-400">Email</label>
            <input type="email" required value={email} onChange={e=>setEmail(e.target.value)} className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase tracking-wide text-neutral-400">Password</label>
            <input type="password" required value={password} onChange={e=>setPassword(e.target.value)} className="bg-neutral-800 border border-neutral-700 rounded px-3 py-2 text-sm" />
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <div className="flex items-center justify-between text-xs text-neutral-400">
            <button type="button" onClick={()=>setMode(mode==='signin'?'signup':'signin')} className="text-indigo-400 hover:underline">{mode==='signin'?'Need an account? Sign up':'Have an account? Sign in'}</button>
            <button type="button" onClick={continueGuest} className="text-neutral-400 hover:text-white">Continue as guest</button>
          </div>
          <button disabled={loading} className="w-full mt-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded py-2 text-sm font-medium">{mode==='signin'?'Sign In':'Create Account'}</button>
        </form>
        <p className="text-[11px] text-neutral-500 leading-relaxed">Guest sessions use a random ID stored only in this browser. Clearing site data or switching devices will lose your resumes.</p>
      </div>
    </div>
  );
};

export const UserBar: React.FC<{user: {mode:'auth'|'guest'; uid:string; email?:string}; onLogout: ()=>void}> = ({ user, onLogout }) => {
  return (
    <div className="flex items-center gap-3 text-xs bg-neutral-800 border border-neutral-700 rounded px-3 py-1">
      {user.mode === 'auth' ? (
        <>
          <span className="text-neutral-300">{user.email}</span>
          <button onClick={onLogout} className="text-red-400 hover:text-red-300">Logout</button>
        </>
      ) : (
        <>
          <span className="text-neutral-400">Guest</span>
          <span className="font-mono text-[10px] text-neutral-500 truncate max-w-[120px]" title={user.uid}>{user.uid}</span>
          <button onClick={onLogout} className="text-indigo-400 hover:text-indigo-300">Sign In</button>
        </>
      )}
    </div>
  );
};
