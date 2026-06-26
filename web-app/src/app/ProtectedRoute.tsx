// Route guard for role-gated areas (e.g. /admin). Authentication itself is enforced one
// level up by the gate in main.tsx (the app router only mounts for an authenticated session,
// or in dev mode where auth is disabled). This component adds ROLE gating + a clean redirect
// so a privileged page never renders for an under-privileged user. The backend independently
// re-checks the principal's permissions on every request — this is UX, not the boundary.
import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useEffectiveRole } from './useRole';

export function ProtectedRoute({ role, children }: { role?: string; children: ReactNode }) {
  const effRole = useEffectiveRole();
  const loc = useLocation();

  if (role && effRole !== role) {
    return <Navigate to="/dashboard" replace state={{ deniedFrom: loc.pathname }} />;
  }
  return <>{children}</>;
}
