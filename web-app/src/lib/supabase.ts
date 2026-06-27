// Supabase client bootstrap.
//
// The URL + anon key are NOT baked into the build — the SPA fetches them from the backend
// at GET /auth/config so credentials live in ONE place (the backend .env). The anon key is
// designed to be public (browser-safe); RLS + the backend's per-user checks are the actual
// security boundary.
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { API_BASE } from '../api';

export interface AuthConfig {
  supabase_url: string;
  supabase_anon_key: string;
  auth_mode: string;
  auth_required: boolean;
}

let _client: SupabaseClient | null = null;
let _config: AuthConfig | null = null;

/** Fetch the public auth config from the backend (cached after first call). */
export async function loadAuthConfig(): Promise<AuthConfig> {
  if (_config) return _config;
  try {
    const r = await fetch(API_BASE + '/auth/config');
    _config = (await r.json()) as AuthConfig;
  } catch {
    // Backend unreachable → behave as if auth is off so the app still renders an error UI.
    _config = { supabase_url: '', supabase_anon_key: '', auth_mode: 'dev', auth_required: false };
  }
  return _config;
}

/** Create (once) and return the Supabase client. Requires loadAuthConfig() to have run. */
export function initSupabase(cfg: AuthConfig): SupabaseClient | null {
  if (_client) return _client;
  if (!cfg.supabase_url || !cfg.supabase_anon_key) return null;
  _client = createClient(cfg.supabase_url, cfg.supabase_anon_key, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      // PKCE: the OAuth redirect returns a short, single-use ?code= instead of the full
      // access/refresh tokens in the URL hash. The browser exchanges that code for the
      // session privately, so JWTs never appear in the URL or browser history.
      flowType: 'pkce',
    },
  });
  return _client;
}

export function getSupabase(): SupabaseClient {
  if (!_client) throw new Error('Supabase client not initialized — call initSupabase() first');
  return _client;
}
