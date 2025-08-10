import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Basic manual chunking to keep initial bundle smaller.
// Firebase especially can inflate the main chunk if eagerly imported.
export default defineConfig(() => ({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react','react-dom'],
          firebase: ['firebase/app','firebase/auth','firebase/firestore']
        }
      }
    },
    chunkSizeWarningLimit: 800 // raise threshold after intentional splitting
  }
}));
