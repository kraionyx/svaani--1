// Admin route wrapper — lazy-loaded so the heavy admin dashboard bundle is only fetched
// for users who actually navigate to /admin (and pass the role guard).
import { AdminDashboard } from '../components/AdminDashboard';

export default function AdminRoute() {
  return (
    <div className="route-page">
      <div className="route-page-head">
        <h1 className="route-page-title">Admin</h1>
        <p className="route-page-sub">Reviews, model/prompt ops, roles, and analytics.</p>
      </div>
      <AdminDashboard />
    </div>
  );
}
