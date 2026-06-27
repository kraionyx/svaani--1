// Global app top bar — brand, provider health, theme switcher, signed-in user. Lifted out
// of the old App monolith so it persists across every route via AppLayout.
import { useStore } from '../store';
import { useAuth } from '../auth';
import * as API from '../api';
import { ConfidenceChip } from '../components/ConfidenceChip';
import { applyCustom, clearCustomInline, loadCustom } from '../theme';

const THEMES = ['mint', 'white', 'dark', 'custom'];

export function TopBar({ onOpenStudio }: { onOpenStudio: (open: boolean) => void }) {
  const s = useStore();
  const { session, signOut } = useAuth();

  const setTheme = (t: string) => {
    document.documentElement.dataset.theme = t;
    localStorage.setItem('svaani-theme', t);
    if (t === 'custom') { applyCustom(loadCustom()); onOpenStudio(true); }
    else { clearCustomInline(); onOpenStudio(false); }
    s.set({} as Partial<ReturnType<typeof useStore.getState>>); // force re-render for the active-theme highlight
  };

  return (
    <header className="topbar">
      <div className="brand">
        <span className="logo">𝓢</span>
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
        )}
        {!session && (
          <label className="ctrl">role
            <select value={s.role} onChange={(e) => { s.set({ role: e.target.value }); API.setRole(e.target.value); }}>
              <option value="doctor">doctor</option><option value="scribe">scribe</option><option value="admin">admin</option>
            </select>
          </label>
        )}
        <div className="seg-theme">{THEMES.map((t) => <button key={t} className={document.documentElement.dataset.theme === t ? 'active' : ''} onClick={() => setTheme(t)}>{t[0].toUpperCase() + t.slice(1)}</button>)}</div>
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
