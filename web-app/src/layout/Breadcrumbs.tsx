// Route-derived breadcrumb trail. Purely presentational — reads the current path and maps
// each segment to a readable label. Dynamic ids (e.g. a session id) fall back to a
// titlecased version of the raw segment.
import { Link, useLocation } from 'react-router-dom';

const LABELS: Record<string, string> = {
  dashboard: 'Scribe Console',
  templates: 'Templates',
  new: 'New',
  patients: 'Patients',
  reports: 'Reports',
  settings: 'Settings',
  profile: 'Profile',
  admin: 'Admin',
  users: 'Users',
  roles: 'Roles',
};

function labelFor(seg: string): string {
  return LABELS[seg] || seg.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function Breadcrumbs() {
  const { pathname } = useLocation();
  const segs = pathname.split('/').filter(Boolean);
  if (segs.length === 0) return null;

  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <Link to="/dashboard" className="crumb">Home</Link>
      {segs.map((seg, i) => {
        const to = '/' + segs.slice(0, i + 1).join('/');
        const last = i === segs.length - 1;
        return (
          <span key={to} className="crumb-group">
            <span className="crumb-sep" aria-hidden="true">›</span>
            {last
              ? <span className="crumb current" aria-current="page">{labelFor(seg)}</span>
              : <Link to={to} className="crumb">{labelFor(seg)}</Link>}
          </span>
        );
      })}
    </nav>
  );
}
