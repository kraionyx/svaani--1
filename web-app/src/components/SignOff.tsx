import { useState } from 'react';
import type { ReviewState } from '../api';

interface Props {
  state: ReviewState | null; hasNote: boolean; signOpen: boolean;
  onTransition: (state: string, extra?: any) => Promise<any>;
  onOpenSign: () => void; onCloseSign: () => void;
  onExport: (fmt: string) => void;
}

export function SignOff(p: Props) {
  const [name, setName] = useState('');
  const can = (target: string) => {
    const map: Record<string, string[]> = {
      in_review: ['draft', 'edited', 'approved'], approved: ['in_review', 'edited'],
    };
    return p.state ? (map[target] || []).includes(p.state) : false;
  };
  const finalized = p.state === 'finalized';

  async function confirm() {
    if (!name.trim()) return;
    try { await p.onTransition('finalized', { signed_by_name: name.trim() }); p.onCloseSign(); } catch { /* toast shown upstream */ }
  }

  return (
    <div className="sign-off-navbar" style={{ 
      display: 'flex', justifyContent: 'space-between', alignItems: 'center', 
      padding: 'var(--space-sm) var(--space-xl)', 
      borderBottom: '1px solid var(--border-soft)',
      background: 'var(--background)',
      width: '100%',
      boxSizing: 'border-box'
    }}>
      <div className="row" style={{ alignItems: 'center', gap: '8px', marginTop: 0 }}>
        <h3 style={{ margin: 0, marginRight: '16px', fontSize: '1rem' }}>Review &amp; Sign-off</h3>
        <button className="btn ghost sm" disabled={!can('in_review')} onClick={() => p.onTransition('in_review')}>Start review</button>
        <button className="btn ghost sm" disabled={!can('approved')} onClick={() => p.onTransition('approved')}>Approve</button>
        <button className="btn sm" disabled={p.state !== 'approved'} onClick={p.onOpenSign}>✎ Finalize &amp; sign</button>
      </div>

      <div className="row wrap" style={{ alignItems: 'center', gap: '8px', marginTop: 0 }}>
        <select 
          className="btn ghost sm" 
          disabled={!finalized} 
          value=""
          onChange={(e) => p.onExport(e.target.value)}
          style={{ appearance: 'none', cursor: 'pointer', outline: 'none', paddingRight: '24px', background: 'var(--surface) url("data:image/svg+xml;utf8,<svg fill=\'%23888\' height=\'24\' viewBox=\'0 0 24 24\' width=\'24\' xmlns=\'http://www.w3.org/2000/svg\'><path d=\'M7 10l5 5 5-5z\'/><path d=\'M0 0h24v24H0z\' fill=\'none\'/></svg>") no-repeat right 4px center', backgroundSize: '16px' }}
        >
          <option value="" disabled hidden>Export</option>
          <option value="json">JSON</option>
          <option value="markdown">Markdown</option>
          <option value="pdf">PDF</option>
          <option value="fhir">FHIR</option>
        </select>
      </div>

      {p.signOpen && (
        <div className="modal" onClick={p.onCloseSign}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3>Finalize &amp; sign</h3>
            <label className="lbl">Signing clinician name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Dr. …" autoFocus />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={confirm}>Sign &amp; finalize</button>
              <button className="btn ghost" onClick={p.onCloseSign}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
