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
    <div className="card panel">
      <div className="step-h"><span className="n">2</span><h3>Review &amp; sign-off</h3></div>
      <div className="row">
        <button className="btn ghost sm" disabled={!can('in_review')} onClick={() => p.onTransition('in_review')}>Start review</button>
        <button className="btn ghost sm" disabled={!can('approved')} onClick={() => p.onTransition('approved')}>Approve</button>
      </div>
      <button className="btn big" disabled={p.state !== 'approved'} onClick={p.onOpenSign}>✎ Finalize &amp; sign</button>
      <p className="hint">Edit &amp; approve the note, then finalize with a signature. Only a finalized note can be exported.</p>

      <div className="step-h"><span className="n">3</span><h3>Export</h3></div>
      <div className="row wrap">
        {['json', 'markdown', 'pdf', 'fhir'].map((f) => (
          <button key={f} className="btn ghost sm" disabled={!finalized} onClick={() => p.onExport(f)}>{f.toUpperCase()}</button>
        ))}
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
