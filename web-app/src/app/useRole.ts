import { useAuth } from '../auth';
import { useStore } from '../store';

/**
 * Effective RBAC role for UI gating only. In JWT mode it derives from the Supabase user's
 * app_metadata/user_metadata `role` claim (default `doctor`); in dev mode it uses the
 * store-backed role selector. This drives nav visibility and route guards, but it is NOT a
 * security boundary — the backend re-verifies the principal's role on every request.
 */
export function useEffectiveRole(): string {
  const { session } = useAuth();
  const storeRole = useStore((s) => s.role);
  if (session) {
    const md = (session.user.app_metadata ?? {}) as Record<string, unknown>;
    const um = (session.user.user_metadata ?? {}) as Record<string, unknown>;
    return String(md.role || um.role || 'doctor').toLowerCase();
  }
  return storeRole;
}
