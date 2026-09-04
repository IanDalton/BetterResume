import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { User } from 'firebase/auth';
import { authStateListener, googleSignIn, logout, emailPasswordSignIn } from '../services/firebase';
import { StatsTab } from './admin/StatsTab';
import { ModelsTab } from './admin/ModelsTab';
import { EvalsTab } from './admin/EvalsTab';
import { FormField, Input, Button, Tabs } from '../components/ui';

const ADMIN_EMAIL = (import.meta.env.VITE_ADMIN_EMAIL || 'daltioan@gmail.com').toLowerCase();

type AdminTab = 'stats' | 'models' | 'evals';

const TABS: Array<{ id: AdminTab; label: string }> = [
  { id: 'stats', label: 'Stats' },
  { id: 'models', label: 'Models' },
  { id: 'evals', label: 'Evals' },
];

export function AdminDashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [tab, setTab] = useState<AdminTab>('stats');
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [signingIn, setSigningIn] = useState(false);

  const handleEmailSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSigningIn(true);
    try {
      await emailPasswordSignIn(email, password);
    } catch (err: any) {
      setError(err.message || 'Sign-in failed');
    } finally {
      setSigningIn(false);
    }
  };

  useEffect(() => {
    const unsub = authStateListener(u => { setUser(u); setAuthReady(true); });
    return () => unsub();
  }, []);

  const isAdminEmail = (user?.email || '').toLowerCase() === ADMIN_EMAIL;

  return (
    <div className="min-h-screen bg-neutral-50 dark:bg-neutral-950 text-neutral-900 dark:text-neutral-100 p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <Link to="/" className="text-xs text-neutral-500 hover:text-neutral-300 focus-ring rounded">&larr; Back to app</Link>
            <h1 className="text-2xl font-semibold tracking-tight">Admin Dashboard</h1>
            <p className="text-sm text-neutral-500">BetterResume generation statistics</p>
          </div>
          {user && (
            <div className="flex items-center gap-3 text-xs">
              <span className="text-neutral-500">{user.email}</span>
              <button onClick={() => logout()} className="text-neutral-600 hover:text-neutral-900 underline-offset-2 hover:underline focus-ring rounded dark:text-neutral-400 dark:hover:text-neutral-100">Sign out</button>
            </div>
          )}
        </header>

        {!authReady && <p className="text-sm text-neutral-500">Checking authentication…</p>}

        {authReady && !user && (
          <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-8 max-w-sm mx-auto space-y-4">
            <p className="text-sm text-neutral-600 dark:text-neutral-400 text-center">Sign in with the admin account to view statistics.</p>
            <Button onClick={() => { setError(null); googleSignIn().catch(e => setError(e.message)); }} className="w-full">
              Sign in with Google
            </Button>
            <div className="flex items-center gap-2 text-xs text-neutral-500">
              <div className="flex-grow h-px bg-neutral-200 dark:bg-neutral-700" /> or <div className="flex-grow h-px bg-neutral-200 dark:bg-neutral-700" />
            </div>
            {/* Fallback for admin accounts that aren't Google-linked, or when Google auth
                is blocked (corporate proxy, browser extension) — Google-only left no way in. */}
            <form onSubmit={handleEmailSignIn} className="space-y-3">
              <FormField label="Email" required>
                <Input type="email" required value={email} onChange={e => setEmail(e.target.value)} />
              </FormField>
              <FormField label="Password" required>
                <Input type="password" required value={password} onChange={e => setPassword(e.target.value)} />
              </FormField>
              <Button type="submit" variant="secondary" loading={signingIn} className="w-full">Sign in</Button>
            </form>
            {error && <p className="text-sm text-red-400 text-center">{error}</p>}
          </div>
        )}

        {authReady && user && !isAdminEmail && (
          <div className="bg-white dark:bg-neutral-900 border border-red-300 dark:border-red-800 rounded-xl p-8 text-center">
            <p className="text-sm text-red-500">Access denied. {user.email} is not authorized to view this page.</p>
          </div>
        )}

        {authReady && user && isAdminEmail && (
          <>
            <Tabs tabs={TABS} value={tab} onChange={setTab} aria-label="Admin sections" />
            {tab === 'stats' && <StatsTab user={user} />}
            {tab === 'models' && <ModelsTab user={user} />}
            {tab === 'evals' && <EvalsTab user={user} onNavigateToModels={() => setTab('models')} />}
          </>
        )}
      </div>
    </div>
  );
}
