import React from 'react';
import { Link } from 'react-router-dom';

export function ThankYou() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100">
      <div className="text-center p-8 max-w-md">
        <div className="mb-6 text-6xl">🎉</div>
        <h1 className="text-3xl font-bold mb-4">Thank You!</h1>
        <p className="text-lg text-neutral-600 dark:text-neutral-400 mb-8">
          Your donation helps keep BetterResume free and running for everyone. We really appreciate your support!
        </p>
        <Link 
          to="/" 
          className="inline-block px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors"
        >
          Back to Resume Builder
        </Link>
      </div>
    </div>
  );
}
