import { useEffect, useState } from 'react';
import { User } from 'firebase/auth';
import { authStateListener, googleSignIn, logout } from '../services/firebase';
import { StatsTab } from './admin/StatsTab';
import { ModelsTab } from './admin/ModelsTab';
import { EvalsTab } from './admin/EvalsTab';

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
            <h1 className="text-2xl font-semibold tracking-tight">Admin Dashboard</h1>
            <p className="text-sm text-neutral-500">BetterResume generation statistics</p>
          </div>
          {user && (
            <div className="flex items-center gap-3 text-xs">
              <span className="text-neutral-500">{user.email}</span>
              <button onClick={() => logout()} className="text-red-400 hover:text-red-300">Sign out</button>
            </div>
          )}
        </header>

        {!authReady && <p className="text-sm text-neutral-500">Checking authentication…</p>}

        {authReady && !user && (
          <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-8 text-center space-y-4">
            <p className="text-sm text-neutral-600 dark:text-neutral-400">Sign in with the admin account to view statistics.</p>
            <button onClick={() => googleSignIn().catch(e => setError(e.message))} className="btn-primary px-4 py-2">
              Sign in with Google
            </button>
            {error && <p className="text-sm text-red-400">{error}</p>}
          </div>
        )}

        {authReady && user && !isAdminEmail && (
          <div className="bg-white dark:bg-neutral-900 border border-red-300 dark:border-red-800 rounded-xl p-8 text-center">
            <p className="text-sm text-red-500">Access denied. {user.email} is not authorized to view this page.</p>
          </div>
        )}

        {authReady && user && isAdminEmail && (
          <>
            <nav className="flex gap-1 border-b border-neutral-200 dark:border-neutral-800">
              {TABS.map(t => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`px-3 py-2 text-sm border-b-2 -mb-px ${tab === t.id
                    ? 'border-primary-500 text-primary-500'
                    : 'border-transparent text-neutral-500 hover:text-neutral-300'}`}
                >
                  {t.label}
                </button>
              ))}
            </nav>
            {tab === 'stats' && <StatsTab user={user} />}
            {tab === 'models' && <ModelsTab user={user} />}
            {tab === 'evals' && <EvalsTab user={user} />}
          </>
        )}
      </div>
    </div>
  );
}
