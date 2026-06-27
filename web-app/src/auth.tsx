// Auth context — wraps Supabase auth state and keeps the REST/WS layer's bearer token in
// sync. useAuth() is safe to call even when auth is disabled (dev mode): it returns a null
// session and no-op signOut via the default context value.
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { Session, User } from '@supabase/supabase-js';
import { getSupabase } from './lib/supabase';
import { setAuthToken } from './api';

interface AuthState {
  session: Session | null;
  user: User | null;
  loading: boolean;
  signOut: () => Promise<void>;
}

const AuthCtx = createContext<AuthState>({
  session: null,
  user: null,
  loading: false,
  signOut: async () => {},
});

export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const sb = getSupabase();
    let active = true;
    // Source of truth on first load: getSession() AWAITS supabase's internal init, which
    // includes detectSessionInUrl — i.e. it parses the OAuth redirect's #access_token /
    // ?code BEFORE resolving. Relying only on onAuthStateChange's INITIAL_SESSION event is
    // a timing assumption that fails on the production build (the event can fire with null
    // before the URL is processed → user bounced back to login despite a valid token in the
    // hash). getSession() is the canonical, redirect-safe way to pick that session up.
    sb.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setAuthToken(data.session?.access_token ?? null);
      setLoading(false);
    });
    // Keep listening for later changes (token refresh, sign-out, sign-in in another tab).
    const { data: sub } = sb.auth.onAuthStateChange((_event, s) => {
      setSession(s);
      setAuthToken(s?.access_token ?? null);
      setLoading(false);
    });
    return () => { active = false; sub.subscription.unsubscribe(); };
  }, []);

  const signOut = async () => {
    await getSupabase().auth.signOut();
    setAuthToken(null);
    setSession(null);
  };

  return (
    <AuthCtx.Provider value={{ session, user: session?.user ?? null, loading, signOut }}>
      {children}
    </AuthCtx.Provider>
  );
}
