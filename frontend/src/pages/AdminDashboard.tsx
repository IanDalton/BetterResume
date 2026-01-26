import React, { useEffect, useState } from 'react';
import { getAdminStats } from '../services/api';
import { useNavigate } from 'react-router-dom';
import { AuthGate } from '../components/AuthGate';
import { authStateListener } from '../services/firebase';

export function AdminDashboard() {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(false); // Stats loading
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState<{mode:'auth'|'guest'; uid:string; email?:string} | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const unsub = authStateListener(u => {
        if (u) {
            setUser({ mode: 'auth', uid: u.uid, email: u.email || undefined });
        } else {
            setUser(null);
        }
        setAuthChecked(true);
    });
    return () => unsub();
  }, []);

  useEffect(() => {
    if (user && user.mode === 'auth') {
        setLoading(true);
        getAdminStats()
        .then(data => {
            setStats(data);
            setLoading(false);
            setError(null);
        })
        .catch(err => {
            console.error(err);
            setError("Failed to load stats. Are you an admin?");
            setLoading(false);
        });
    }
  }, [user]);

  if (!authChecked) {
      return <div className="p-8 text-center">Checking permissions...</div>;
  }

  if (!user || user.mode === 'guest') {
      return (
          <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
              <h1 className="text-2xl font-bold mb-4">Admin Access Required</h1>
              <p className="mb-8 text-gray-600 dark:text-gray-400">Please sign in to view the dashboard.</p>
              <div className="relative h-16 w-full">
                {/* We render AuthGate which will likely pop up its modal immediately because we aren't authed? 
                    Actually AuthGate only opens if instructed or guest logic triggers. 
                    We'll pass forceOpenSignal to ensure it opens.
                */}
                <AuthGate 
                    onResolved={(u) => {
                        if (u.mode === 'auth') setUser(u);
                    }} 
                    forceOpenSignal={Date.now()} 
                />
              </div>
              <button onClick={() => navigate('/')} className="mt-8 text-blue-500 hover:underline">Return Home</button>
          </div>
      );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 flex flex-col">
      <header className="bg-white dark:bg-gray-800 shadow p-4 flex justify-between items-center">
        <h1 className="text-xl font-bold">Admin Dashboard</h1>
        <div className="flex items-center gap-4">
            <span className="text-sm text-gray-500">{user.email}</span>
            <button onClick={() => navigate('/')} className="text-blue-500 hover:underline">
            Back to Home
            </button>
        </div>
      </header>

      <main className="flex-1 p-8">
        <div className="max-w-7xl mx-auto">
          {loading && <p className="text-center text-gray-500">Loading stats...</p>}
          {error && <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">{error}</div>}
          
          {stats && !loading && (
            <div className="space-y-8">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6">
                <StatCard title="Total Users" value={stats.users} />
                <StatCard title="Resume Requests" value={stats.resume_requests} />
                <StatCard title="Job Experiences" value={stats.job_experiences} />
                <StatCard title="Files Stored" value={stats.files_stored} />
                <StatCard title="Resumes Generated" value={stats.resumes_generated} />
                </div>

                {stats.recent_activity && stats.recent_activity.length > 0 && (
                    <div className="bg-white dark:bg-gray-800 shadow rounded-lg overflow-hidden">
                        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
                            <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100">Recent Activity</h3>
                        </div>
                        <ul className="divide-y divide-gray-200 dark:divide-gray-700">
                            {stats.recent_activity.map((item: any, idx: number) => (
                                <li key={idx} className="px-6 py-4 hover:bg-gray-50 dark:hover:bg-gray-750">
                                    <div className="flex justify-between">
                                        <div>
                                            <p className="text-sm font-medium text-blue-600 dark:text-blue-400">{item.type}</p>
                                            <p className="text-sm text-gray-500 dark:text-gray-400">User: {item.user_id}</p>
                                        </div>
                                        <div className="text-sm text-gray-500 dark:text-gray-400">
                                            {new Date(item.date).toLocaleString()}
                                        </div>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function StatCard({ title, value }: { title: string, value: number }) {
    return (
        <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow border border-gray-200 dark:border-gray-700">
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">{title}</h3>
            <p className="mt-2 text-3xl font-semibold">{value !== undefined ? value.toLocaleString() : '-'}</p>
        </div>
    )
}
