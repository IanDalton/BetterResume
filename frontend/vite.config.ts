import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// If deploying to GitHub Pages project site (https://<user>.github.io/BetterResume/)
// we need base to match repo name. We use GITHUB_PAGES env flag set in workflow.

export default defineConfig(() => ({
  plugins: [react()],
}));
