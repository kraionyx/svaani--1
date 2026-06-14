import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' so the built bundle works whether served at / or mounted under /ui.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: { port: 5173 },
});
