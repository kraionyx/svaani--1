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
    // onAuthStateChange fires INITIAL_SESSION immediately (Supabase v2), which already
    // includes any session resolved from the OAuth callback URL. Using getSession()
    // alongside it creates a race: getSession() can resolve with null before the URL
    // hash/code is processed, setting loading=false and flashing the login page.
    const { data: sub } = sb.auth.onAuthStateChange((_event, s) => {
      setSession(s);
      setAuthToken(s?.access_token ?? null);
      setLoading(false);
    });
    return () => sub.subscription.unsubscribe();
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
