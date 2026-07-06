/**** Tailwind Config ****/
const colors = require('tailwindcss/colors');

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{ts,tsx,js,jsx}'
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter Variable', 'Inter', 'system-ui', 'sans-serif']
      },
      colors: {
        // Alias to the existing brand red so primary-* is pixel-identical to
        // the red-* classes already used throughout the app.
        primary: colors.red
      },
      keyframes: {
        progressMove: {
          '0%': { backgroundPosition: '0% 0' },
          '100%': { backgroundPosition: '200% 0' }
        }
      },
      animation: {
        progressMove: 'progressMove 2s linear infinite'
      }
    }
  },
  plugins: [require('tailwindcss-animate')]
};
