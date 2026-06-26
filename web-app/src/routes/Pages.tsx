// Lightweight route pages. Profile/Settings are wired to real state; Templates/Patients/
// Reports are polished scaffolds that route correctly today and get fleshed out in later
// workstreams (the dynamic template builder lands on /templates/new and /templates/:id).
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth';
import { useStore } from '../store';
import { useEffectiveRole } from '../app/useRole';

function PageHead({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="route-page-head">
      <h1 className="route-page-title">{title}</h1>
      {subtitle && <p className="route-page-sub">{subtitle}</p>}
    </div>
  );
}

function ComingSoon({ title, subtitle, note, cta }: { title: string; subtitle: string; note: string; cta?: ReactNode }) {
  return (
    <div className="route-page">
      <PageHead title={title} subtitle={subtitle} />
      <div className="route-empty card">
        <div className="route-empty-icon" aria-hidden="true">⚒</div>
        <h3>In progress</h3>
        <p>{note}</p>
        {cta}
      </div>
    </div>
  );
}

export function TemplatesPage() {
  const role = useEffectiveRole();
  return (
    <ComingSoon
      title="Templates"
      subtitle="Consultation note templates for your specialties."
      note="The dynamic, drag-and-drop template builder is landing in this route group. Doctors and admins will be able to assemble note structures from reusable field blocks."
      cta={role === 'admin' || role === 'doctor'
        ? <Link to="/templates/new" className="route-cta">+ New template</Link>
        : <span className="route-muted">Ask an admin to grant you the doctor role to author templates.</span>}
    />
  );
}

export function TemplateBuilderPage() {
  return (
    <ComingSoon
      title="Template builder"
      subtitle="Compose a consultation template from field blocks."
      note="Drag-and-drop builder with standard scribe text boxes plus custom fields. This is the next workstream."
      cta={<Link to="/templates" className="route-cta ghost">← Back to templates</Link>}
    />
  );
}

export function PatientsPage() {
  return (
    <ComingSoon
      title="Patients"
      subtitle="Patient records linked to your consultations."
      note="A searchable patient index with per-patient consultation history will live here."
    />
  );
}

export function ReportsPage() {
  return (
    <ComingSoon
      title="Reports"
      subtitle="Operational and clinical documentation analytics."
      note="Throughput, turnaround, and review-quality reporting will surface here."
    />
  );
}

export function SettingsPage() {
  const s = useStore();
  const setMode = (v: 'realtime' | 'batch' | 'auto' | 'hybrid') => { s.set({ modeChoice: v }); localStorage.setItem('svaani-mode', v); };
  return (
    <div className="route-page">
      <PageHead title="Settings" subtitle="Preferences for capture and processing." />
      <div className="card route-card">
        <label className="route-field">
          <span className="route-field-label">Default capture mode</span>
          <select value={s.modeChoice} onChange={(e) => setMode(e.target.value as 'realtime' | 'batch' | 'auto' | 'hybrid')}>
            <option value="realtime">Realtime (streaming)</option>
            <option value="batch">Batch (diarized)</option>
            <option value="auto">Auto</option>
            <option value="hybrid">Hybrid</option>
          </select>
        </label>
        <p className="route-muted">Theme is in the top bar. More workspace preferences are coming.</p>
      </div>
    </div>
  );
}

export function ProfilePage() {
  const { session, signOut } = useAuth();
  const role = useEffectiveRole();
  const email = session?.user.email ?? 'dev session (auth disabled)';
  return (
    <div className="route-page">
      <PageHead title="Profile" subtitle="Your account and access." />
      <div className="card route-card">
        <div className="route-kv"><span>Email</span><b>{email}</b></div>
        <div className="route-kv"><span>Role</span><b className="route-role-pill">{role}</b></div>
        {session && <div className="route-kv"><span>User ID</span><code>{session.user.id}</code></div>}
        {session && (
          <button className="route-cta danger" onClick={() => signOut()}>Sign out</button>
        )}
      </div>
    </div>
  );
}

export function NotFound() {
  return (
    <div className="route-404">
      <div className="route-404-code" aria-hidden="true">404</div>
      <h2>Page not found</h2>
      <p>The page you're looking for doesn't exist or has moved.</p>
      <Link to="/dashboard" className="route-cta">Back to Scribe Console</Link>
    </div>
  );
}
