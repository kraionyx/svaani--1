// Lightweight route pages. Profile/Settings are wired to real state; Templates/Patients/
// Reports are polished scaffolds that route correctly today and get fleshed out in later
// workstreams (the dynamic template builder lands on /templates/new and /templates/:id).
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth';
import { useStore } from '../store';
import { useEffectiveRole } from '../app/useRole';
import { UserCircle, Sliders, Package, Shield, Settings as SettingsIcon, Users as UsersIcon, FileText, CreditCard, Upload, Sparkles } from 'lucide-react';

function PageHead({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-8 shrink-0">
      <h1 className="text-[28px] font-semibold text-slate-900 tracking-tight">{title}</h1>
      {subtitle && <p className="text-[15px] text-slate-500 mt-2 font-medium">{subtitle}</p>}
    </div>
  );
}

function ComingSoon({ title, subtitle, note, cta }: { title: string; subtitle: string; note: string; cta?: ReactNode }) {
  return (
    <div className="flex-1 p-10 max-w-6xl w-full flex flex-col mx-auto overflow-hidden">
      <PageHead title={title} subtitle={subtitle} />
      
      <div className="flex-1 flex items-center justify-center pt-8 pb-16">
        <div className="bg-white rounded-3xl border border-slate-200/60 p-12 shadow-xl shadow-slate-200/30 max-w-2xl w-full text-center relative overflow-hidden flex flex-col items-center">
          
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full h-1.5 bg-gradient-to-r from-transparent via-[#5b32f5] to-transparent opacity-60" />
          <div className="absolute -top-32 -left-32 w-64 h-64 bg-[#5b32f5]/10 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-32 -right-32 w-64 h-64 bg-sky-400/10 rounded-full blur-3xl pointer-events-none" />
          
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-50 to-sky-50 text-[#5b32f5] flex items-center justify-center mb-6 shadow-sm border border-indigo-100/50">
            <Sparkles size={36} strokeWidth={1.5} />
          </div>
          
          <h3 className="text-2xl font-semibold text-slate-800 mb-4 tracking-tight">Svaani is brewing...</h3>
          <p className="text-slate-500 text-[16px] leading-relaxed mb-10 max-w-lg mx-auto">
            {note}
          </p>
          
          {cta && (
            <div className="mt-2 relative z-10">
              {cta}
            </div>
          )}
        </div>
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
        ? <Link to="/templates/new" className="px-6 py-2.5 bg-[#5b32f5] text-white rounded-xl text-[15px] font-medium hover:bg-[#4b26d1] transition-all shadow-md hover:shadow-lg inline-block">+ New template</Link>
        : <span className="text-slate-400 text-[15px] font-medium">Ask an admin to grant you the doctor role to author templates.</span>}
    />
  );
}

export function TemplateBuilderPage() {
  return (
    <ComingSoon
      title="Template builder"
      subtitle="Compose a consultation template from field blocks."
      note="Drag-and-drop builder with standard scribe text boxes plus custom fields. This is the next workstream."
      cta={<Link to="/templates" className="px-6 py-2.5 border border-slate-200 bg-white rounded-xl text-[15px] font-medium text-slate-700 hover:bg-slate-50 transition-all shadow-sm inline-block">← Back to templates</Link>}
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
  const [activeTab, setActiveTab] = useState('account');
  const s = useStore();
  const { session } = useAuth();
  const setMode = (v: 'realtime' | 'batch' | 'auto' | 'hybrid') => { s.set({ modeChoice: v }); localStorage.setItem('svaani-mode', v); };

  const PERSONAL_NAV = [
    { id: 'account', label: 'Account', icon: UserCircle },
    { id: 'preferences', label: 'Preferences', icon: Sliders },
    { id: 'plan', label: 'Plan & Usage', icon: Package },
    { id: 'security', label: 'Login & Security', icon: Shield },
  ];

  const WORKSPACE_NAV = [
    { id: 'defaults', label: 'Defaults', icon: SettingsIcon },
    { id: 'org', label: 'Org Management', icon: UsersIcon },
    { id: 'letterhead', label: 'Manage Letterhead', icon: FileText },
    { id: 'billing', label: 'Billing', icon: CreditCard },
  ];

  return (
    <div className="flex h-full w-full bg-[#f8fafc]">
      {/* Settings Sidebar */}
      <div className="w-64 border-r border-slate-200 p-6 flex flex-col overflow-y-auto bg-white shrink-0">
        <h2 className="text-xl font-semibold text-slate-800 mb-6">Settings</h2>
        
        <div className="mb-6">
          <div className="text-[13px] font-medium text-slate-500 mb-3">Personal</div>
          <div className="flex flex-col gap-1">
            {PERSONAL_NAV.map(n => (
              <button 
                key={n.id}
                onClick={() => setActiveTab(n.id)}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-[14px] font-medium transition-colors ${activeTab === n.id ? 'bg-[#f4f3ff] text-[#5b32f5]' : 'text-slate-600 hover:bg-slate-50'}`}
              >
                <n.icon size={18} className={activeTab === n.id ? 'text-[#5b32f5]' : 'text-slate-400'} />
                {n.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <div className="text-[13px] font-medium text-slate-500 mb-3">Workspace</div>
          <div className="flex flex-col gap-1">
            {WORKSPACE_NAV.map(n => (
              <button 
                key={n.id}
                onClick={() => setActiveTab(n.id)}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-[14px] font-medium transition-colors ${activeTab === n.id ? 'bg-[#f4f3ff] text-[#5b32f5]' : 'text-slate-600 hover:bg-slate-50'}`}
              >
                <n.icon size={18} className={activeTab === n.id ? 'text-[#5b32f5]' : 'text-slate-400'} />
                {n.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Settings Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {activeTab === 'account' ? (
          <div className="flex flex-col h-full max-w-6xl w-full p-8">
            <h1 className="text-[22px] font-semibold text-slate-900 mb-8 shrink-0">Account Settings</h1>
            
            <div className="bg-white rounded-xl border border-slate-200 p-8 shadow-sm flex-1">
              <h2 className="text-lg font-semibold text-slate-800 mb-6">Profile Information</h2>
              
              <div className="grid grid-cols-2 gap-6 items-center mb-6">
                <div className="flex items-center gap-6">
                  <div className="w-20 h-20 rounded-full bg-[#d8b4fe] text-[#6b21a8] flex items-center justify-center text-3xl font-medium shrink-0 shadow-sm">
                    A
                  </div>
                  <div>
                    <button className="flex items-center gap-2 px-4 py-2 border border-slate-200 rounded-lg text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors mb-2">
                      <Upload size={16} /> Upload Photo
                    </button>
                    <p className="text-[13px] text-slate-500">At least 256×256 PNG or JPG file. Max 2MB.</p>
                  </div>
                </div>
                <div>
                  <label className="block text-[13px] font-medium text-slate-700 mb-1.5">Title</label>
                  <select className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#5b32f5]">
                    <option>Mr</option>
                    <option>Dr</option>
                    <option>Ms</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-6 mb-6">
                <div>
                  <label className="block text-[13px] font-medium text-slate-700 mb-1.5">Full Name</label>
                  <input type="text"  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#5b32f5]" />
                </div>
                <div>
                  <label className="block text-[13px] font-medium text-slate-700 mb-1.5">Designation</label>
                  <input type="text" className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#5b32f5]" />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-6">
                <div>
                  <label className="block text-[13px] font-medium text-slate-700 mb-1.5">Phone Number</label>
                  <div className="flex">
                    <div className="flex items-center px-3 border border-slate-200 border-r-0 rounded-l-lg bg-slate-50 text-sm text-slate-700">
                      🇮🇳 +91
                    </div>
                    <input type="text" defaultValue="" className="flex-1 px-3 py-2 border border-slate-200 rounded-r-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#5b32f5]" />
                  </div>
                </div>
                <div>
                  <label className="block text-[13px] font-medium text-slate-700 mb-1.5">Email</label>
                  <input type="text" value={session?.user?.email || ''} readOnly disabled className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm bg-slate-50 text-slate-500" />
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3 shrink-0 pt-6">
              <button className="px-5 py-2 border border-slate-200 bg-white rounded-lg text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors">Cancel</button>
              <button className="px-5 py-2 bg-[#5b32f5] text-white rounded-lg text-sm font-medium hover:bg-[#4b26d1] transition-colors shadow-sm">Save</button>
            </div>
          </div>
        ) : activeTab === 'defaults' ? (
          <div className="max-w-4xl">
             <h1 className="text-[22px] font-semibold text-slate-900 mb-8">Workspace Defaults</h1>
             
             <div className="bg-white rounded-xl border border-slate-200 p-8 shadow-sm mb-6">
               <label className="block text-[13px] font-medium text-slate-700 mb-1.5">Default capture mode</label>
                <select value={s.modeChoice} onChange={(e) => setMode(e.target.value as any)} className="w-full max-w-xs px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#5b32f5]">
                  <option value="realtime">Realtime (streaming)</option>
                  <option value="batch">Batch (diarized)</option>
                  <option value="auto">Auto</option>
                  <option value="hybrid">Hybrid</option>
                </select>
             </div>
             
             <div className="bg-white rounded-xl border border-slate-200 p-8 shadow-sm">
                <h3 className="text-[15px] font-semibold text-slate-800 mb-6">System Health</h3>
                <div className="flex flex-col gap-4 max-w-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-[14px] text-slate-600 font-medium">Speech-to-Text (Sarvam)</span>
                    <span className={`pill ${s.health?.sarvam === 'live' ? 'live' : 'mock'}`}><span className="d" />{s.health?.sarvam || 'Checking…'}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[14px] text-slate-600 font-medium">LLM (Vertex)</span>
                    <span className={`pill ${s.health?.vertex === 'live' ? 'live' : 'mock'}`}><span className="d" />{s.health?.vertex || 'Checking…'}</span>
                  </div>
                </div>
             </div>
          </div>
        ) : (
          <div className="max-w-4xl">
            <h1 className="text-[22px] font-semibold text-slate-900 mb-8 capitalize">{activeTab.replace('-', ' ')} Settings</h1>
            <div className="bg-white rounded-xl border border-slate-200 p-8 shadow-sm flex items-center justify-center text-slate-400 py-24">
               Coming soon...
            </div>
          </div>
        )}
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
          <button className="px-5 py-2.5 mt-4 bg-red-50 text-red-600 border border-red-100 rounded-xl text-sm font-medium hover:bg-red-100 transition-colors w-full" onClick={() => signOut()}>Sign out</button>
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
      <Link to="/dashboard" className="px-6 py-2.5 bg-[#5b32f5] text-white rounded-xl text-[15px] font-medium hover:bg-[#4b26d1] transition-all shadow-md hover:shadow-lg inline-block mt-4">Back to Scribe Console</Link>
    </div>
  );
}
