// Primary navigation rail. Role-aware: admin-only destinations are hidden for non-admins
// (defence-in-depth backs this up at the route guard + backend). Uses NavLink so the
// active route is highlighted automatically.
import { NavLink } from 'react-router-dom';
import { useEffectiveRole } from '../app/useRole';

interface NavItem { to: string; label: string; icon: string; adminOnly?: boolean; }

const NAV: NavItem[] = [
  { to: '/dashboard', label: 'Scribe Console', icon: '◉' },
  { to: '/templates', label: 'Templates', icon: '▤' },
  { to: '/patients', label: 'Patients', icon: '♥' },
  { to: '/reports', label: 'Reports', icon: '▦' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
  { to: '/profile', label: 'Profile', icon: '☺' },
  { to: '/admin', label: 'Admin', icon: '⛨', adminOnly: true },
];

export function Sidebar() {
  const role = useEffectiveRole();
  return (
    <nav className="app-sidebar" aria-label="Primary navigation">
      <ul className="app-nav">
        {NAV.filter((n) => !n.adminOnly || role === 'admin').map((n) => (
          <li key={n.to}>
            <NavLink to={n.to} className={({ isActive }) => `app-nav-link${isActive ? ' active' : ''}`}>
              <span className="app-nav-icon" aria-hidden="true">{n.icon}</span>
              <span className="app-nav-label">{n.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="app-sidebar-foot">
        <span className="app-nav-role" title="Your access role">{role}</span>
      </div>
    </nav>
  );
}
