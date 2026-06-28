import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AppRouter } from './app/router';
import { AdminPage } from './pages/AdminPage';
import { LoginPage } from './pages/LoginPage';
import { AuthProvider, useAuth } from './auth';
import { loadAuthConfig, initSupabase, type AuthConfig } from './lib/supabase';
import { applyCustom, loadCustom } from './theme';
import './styles.css';

// Dev (Vite :5173): pathname is /admin1
// Prod (FastAPI /admin1 → serves SPA): pathname is /admin1 or /admin1/
// Also accept /app/admin1 — the SPA's base is /app/, so a relative link from the main app
// can land there; without this it would fall through to the gated app instead of the console.
const isAdmin = /(^|\/)admin1(\/|$)/.test(window.location.pathname);

if (!isAdmin) {
  const theme = localStorage.getItem('svaani-theme') || 'mint';
  document.documentElement.dataset.theme = theme;
  if (theme === 'custom') applyCustom(loadCustom());
}

// Global error reporter — POSTs uncaught errors to backend (non-blocking)
function reportError(type: string, message: string, stack?: string) {
  try {
    fetch('/admin1/api/errors/frontend', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        error_type: type,
        error_message: message,
        stack_trace: stack,
        endpoint: window.location.pathname,
        browser_info: { url: window.location.href, ua: navigator.userAgent },
      }),
    }).catch(() => {});
  } catch { /* never throw from error handler */ }
}

window.addEventListener('error', (e) => {
  reportError(e.error?.name || 'Error', e.message, e.error?.stack);
});

window.addEventListener('unhandledrejection', (e) => {
  const err = e.reason;
  reportError(err?.name || 'UnhandledRejection', String(err?.message || err), err?.stack);
});

// Minimal full-screen splash while we resolve auth config / session.
function Splash({ label = 'Waking up Svaani…' }: { label?: string }) {
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: 'var(--bg)', color: 'var(--muted)' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 34, color: 'var(--accent)' }}>𝓢</span>
        <span>{label}</span>
      </div>
    </div>
  );
}

// Inside the AuthProvider: render the routed app once authenticated, else the login page.
function Gated() {
  const { session, loading } = useAuth();
  if (loading) return <Splash label="Signing you in…" />;
  // Bypassing login for now:
  if (!session) return <LoginPage />;
  return <AppRouter />;
}

// Top-level: fetch the public auth config, then decide whether to gate behind login.
// The admin dashboard (/admin1) keeps its own password auth and is never gated here.
function Root() {
  const [cfg, setCfg] = useState<AuthConfig | null>(null);

  useEffect(() => {
    loadAuthConfig().then((c) => {
      if (c.auth_required) initSupabase(c);
      setCfg(c);
    });
  }, []);

  if (isAdmin) return <AdminPage />;
  if (!cfg) return <Splash />;
  if (!cfg.auth_required) return <AppRouter />;      // dev mode (SCRIBE_AUTH_MODE=dev): no login
  return (
    <AuthProvider>
      <Gated />
    </AuthProvider>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
