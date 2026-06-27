import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

// Dev-only: Vite refuses to serve paths outside `base` (/app/). The admin SPA must be
// reachable at /admin1, so internally rewrite that request to the SPA index. The browser
// URL stays /admin1 (so main.tsx's isAdmin check still fires); /admin1/api/* is left for
// the proxy. Production serves /admin1 via FastAPI (app/main.py) instead.
function adminDevRoute(): Plugin {
  return {
    name: 'admin-dev-route',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = req.url || '';
        if (url === '/admin1' || url === '/admin1/' || url.startsWith('/admin1?')) {
          req.url = '/app/';
        }
        next();
      });
    },
  };
}

// base '/app/' so built asset paths are absolute — SPA works at both /app and /admin1.
export default defineConfig({
  plugins: [react(), adminDevRoute()],
  base: '/app/',
  // Force a SINGLE React instance. Without dedupe, Vite's dep optimizer pre-bundled React
  // twice (a standalone `react` chunk plus a copy inlined into the react-dom chunk). The two
  // copies each have their own internal dispatcher, so a hook resolved from one while react-dom
  // set the dispatcher on the other read `null` → "Cannot read properties of null (reading
  // 'useState')" and crashed every authenticated load. dedupe + a pinned optimizeDeps entry
  // keep React as one module across the whole graph.
  resolve: { dedupe: ['react', 'react-dom'] },
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-dom/client', 'react/jsx-runtime'],
  },
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    port: 5173,
    allowedHosts: ['svaani.kraionyx.com'],
    proxy: {
      '/admin1/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
