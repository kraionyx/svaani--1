// Global app top bar — brand, provider health, theme switcher, signed-in user. Lifted out
// of the old App monolith so it persists across every route via AppLayout.
import { useStore } from '../store';
import { useAuth } from '../auth';
import * as API from '../api';
import { ConfidenceChip } from '../components/ConfidenceChip';

export function TopBar() {
  const s = useStore();
  const { session, signOut } = useAuth();

  return (
    <header className="topbar">
      <div className="brand">
        
        <div className="brand-id">
          <b>Svaani<span className="dot">.</span></b>
          <span className="sub">AI Medical Scribe — a faithful scribe, never prescribes</span>
        </div>
        
      </div>
      <div className="topctrls">
        <span className={`pill ${s.health?.sarvam === 'live' ? 'live' : 'mock'}`}><span className="d" />STT: {s.health?.sarvam || '…'}</span>
        <span className={`pill ${s.health?.vertex === 'live' ? 'live' : 'mock'}`}><span className="d" />LLM: {s.health?.vertex || '…'}</span>
        {s.confidenceBand && (
          <ConfidenceChip band={s.confidenceBand} reasons={s.confidenceReasons} />
        )}sarva
        {!session && (
          <label className="ctrl">role
            <select value={s.role} onChange={(e) => { s.set({ role: e.target.value }); API.setRole(e.target.value); }}>
              <option value="doctor">doctor</option><option value="scribe">scribe</option><option value="admin">admin</option>
            </select>
          </label>
        )}
        {session && (
          <span className="ctrl" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span title={session.user.email || ''} style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>
              {session.user.email}
            </span>
            <button onClick={() => signOut()}>Sign out</button>
          </span>
        )}
      </div>
    </header>
  );
}
