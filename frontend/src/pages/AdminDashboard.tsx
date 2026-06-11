import React, { useEffect, useMemo, useState } from 'react';
import { User } from 'firebase/auth';
import { authStateListener, googleSignIn, logout } from '../services/firebase';
import { fetchAdminStats, AdminStats } from '../services/api';

const ADMIN_EMAIL = (import.meta.env.VITE_ADMIN_EMAIL || 'daltioan@gmail.com').toLowerCase();

function StatCard({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
      <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="text-2xl font-semibold mt-1">{value}</p>
      {hint && <p className="text-[11px] text-neutral-500 mt-1">{hint}</p>}
    </div>
  );
}

function BarChart({ data, title }: { data: Array<{ day: string; count: number }>; title: string }) {
  const max = Math.max(1, ...data.map(d => d.count));
  return (
    <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
      <h3 className="text-sm font-medium mb-3">{title}</h3>
      {data.length === 0 ? (
        <p className="text-xs text-neutral-500">No data yet.</p>
      ) : (
        <div className="flex items-end gap-1 h-32">
          {data.map(d => (
            <div key={d.day} className="flex-1 flex flex-col items-center justify-end h-full" title={`${d.day}: ${d.count}`}>
              <div
                className="w-full bg-blue-500/80 dark:bg-blue-400/80 rounded-t"
                style={{ height: `${Math.max(4, (d.count / max) * 100)}%` }}
              />
              <span className="text-[9px] text-neutral-500 mt-1 rotate-0 truncate w-full text-center">
                {d.day.slice(5)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CountTable({ title, rows, keyLabel }: { title: string; rows: Array<{ label: string; count: number }>; keyLabel: string }) {
  return (
    <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
      <h3 className="text-sm font-medium mb-3">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-xs text-neutral-500">No data yet.</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-neutral-500">
              <th className="pb-1 font-normal">{keyLabel}</th>
              <th className="pb-1 font-normal text-right">Count</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.label} className="border-t border-neutral-100 dark:border-neutral-800">
                <td className="py-1 truncate max-w-[200px]" title={r.label}>{r.label}</td>
                <td className="py-1 text-right font-mono">{r.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function AdminDashboard() {
  const [user, setUser] = useState<User | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(30);

  useEffect(() => {
    const unsub = authStateListener(u => { setUser(u); setAuthReady(true); });
    return () => unsub();
  }, []);

  const isAdminEmail = (user?.email || '').toLowerCase() === ADMIN_EMAIL;

  useEffect(() => {
    if (!user || !isAdminEmail) { setStats(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    user.getIdToken()
      .then(token => fetchAdminStats(token, days))
      .then(s => { if (!cancelled) setStats(s); })
      .catch(e => {
        if (cancelled) return;
        setError(e.message === 'forbidden' ? 'Access denied: this account is not authorized.' : `Failed to load stats: ${e.message}`);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [user, isAdminEmail, days]);

  const successRate = useMemo(() => {
    const r = stats?.totals.success_rate;
    return r == null ? '—' : `${(r * 100).toFixed(1)}%`;
  }, [stats]);

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
            <div className="flex items-center gap-2 text-xs">
              <span className="text-neutral-500">Window:</span>
              {[7, 30, 90].map(d => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={`px-2 py-1 rounded border ${days === d
                    ? 'border-blue-500 text-blue-500'
                    : 'border-neutral-300 dark:border-neutral-700 text-neutral-500'}`}
                >
                  {d}d
                </button>
              ))}
              {loading && <span className="text-neutral-500 ml-2">Loading…</span>}
            </div>

            {error && <p className="text-sm text-red-400">{error}</p>}

            {stats && (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <StatCard label="Resumes generated" value={stats.totals.generations} hint={`${stats.totals.successful_generations} successful`} />
                  <StatCard label="Success rate" value={successRate} hint={`avg ${Math.round(stats.totals.avg_duration_ms / 1000)}s per resume`} />
                  <StatCard label="Resume requests" value={stats.totals.resume_requests} hint={`${stats.totals.requesting_users} unique users`} />
                  <StatCard label="Registered users" value={stats.totals.users} />
                </div>

                <div className="grid md:grid-cols-2 gap-4">
                  <BarChart data={stats.generations_per_day} title={`Generations per day (last ${days}d)`} />
                  <BarChart data={stats.requests_per_day} title={`Requests per day (last ${days}d)`} />
                </div>

                <div className="grid md:grid-cols-3 gap-4">
                  <CountTable title="By model" keyLabel="Model" rows={stats.by_model.map(m => ({ label: m.model, count: m.count }))} />
                  <CountTable title="By format" keyLabel="Format" rows={stats.by_format.map(f => ({ label: f.format, count: f.count }))} />
                  <CountTable title="By language" keyLabel="Language" rows={stats.by_language.map(l => ({ label: l.language, count: l.count }))} />
                </div>

                <div className="grid md:grid-cols-2 gap-4">
                  <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
                    <h3 className="text-sm font-medium mb-3">Top users</h3>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-neutral-500">
                          <th className="pb-1 font-normal">User</th>
                          <th className="pb-1 font-normal text-right">Requests</th>
                          <th className="pb-1 font-normal text-right">Last request</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stats.top_users.map(u => (
                          <tr key={u.user_id} className="border-t border-neutral-100 dark:border-neutral-800">
                            <td className="py-1 font-mono truncate max-w-[140px]" title={u.user_id}>{u.user_id}</td>
                            <td className="py-1 text-right font-mono">{u.requests}</td>
                            <td className="py-1 text-right text-neutral-500">{u.last_request.slice(0, 16)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
                    <h3 className="text-sm font-medium mb-3">Donations</h3>
                    {stats.donations.by_currency.length === 0 ? (
                      <p className="text-xs text-neutral-500">No donations recorded.</p>
                    ) : (
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-left text-neutral-500">
                            <th className="pb-1 font-normal">Currency</th>
                            <th className="pb-1 font-normal text-right">Count</th>
                            <th className="pb-1 font-normal text-right">Total</th>
                          </tr>
                        </thead>
                        <tbody>
                          {stats.donations.by_currency.map(d => (
                            <tr key={d.currency} className="border-t border-neutral-100 dark:border-neutral-800">
                              <td className="py-1 uppercase">{d.currency}</td>
                              <td className="py-1 text-right font-mono">{d.count}</td>
                              <td className="py-1 text-right font-mono">{(d.total_amount / 100).toFixed(2)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>

                <div className="bg-white dark:bg-neutral-900 border border-neutral-200 dark:border-neutral-700 rounded-xl p-4 shadow-sm">
                  <h3 className="text-sm font-medium mb-3">Recent resume requests</h3>
                  {stats.recent_requests.length === 0 ? (
                    <p className="text-xs text-neutral-500">No requests yet.</p>
                  ) : (
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-neutral-500">
                          <th className="pb-1 font-normal">When</th>
                          <th className="pb-1 font-normal">User</th>
                          <th className="pb-1 font-normal">Job posting (preview)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stats.recent_requests.map((r, i) => (
                          <tr key={i} className="border-t border-neutral-100 dark:border-neutral-800 align-top">
                            <td className="py-1 whitespace-nowrap text-neutral-500">{r.created_at.slice(0, 16)}</td>
                            <td className="py-1 font-mono truncate max-w-[120px]" title={r.user_id}>{r.user_id}</td>
                            <td className="py-1 text-neutral-600 dark:text-neutral-400">{r.job_posting_preview}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
