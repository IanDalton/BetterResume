import React from 'react';

export function Footer() {
  return (
    <footer className="fixed bottom-0 left-0 right-0 z-40 bg-neutral-900/90 backdrop-blur border-t border-neutral-800 text-neutral-300">
      <div className="max-w-5xl mx-auto px-4 py-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs sm:text-sm">
        <span className="whitespace-pre">Better resume </span>

        <a
          href="https://www.linkedin.com/in/ian-dalton-data"
          target="_blank"
          rel="noopener noreferrer"
          className="text-red-400 hover:text-red-300 underline-offset-2 hover:underline"
        >
          linkedin.com/in/ian-dalton-data
        </a>
      </div>
    </footer>
  );
}
