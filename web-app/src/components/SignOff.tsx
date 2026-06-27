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
    <div className="flex flex-col gap-3 mt-6">
      <div className="flex items-center gap-3 mb-1 opacity-80">
        <span className="flex items-center justify-center w-6 h-6 rounded-full bg-sky-100 text-sky-600 text-xs font-bold">2</span>
        <h3 className="text-[11px] font-bold tracking-[1.5px] text-slate-500 uppercase">Review &amp; sign-off</h3>
      </div>
      <div className="flex gap-2">
        <button className="flex-1 py-2.5 rounded-xl text-[13px] font-semibold text-sky-700 bg-sky-50 hover:bg-sky-100 transition-colors disabled:opacity-50 disabled:bg-slate-50 disabled:text-slate-400 active:scale-[0.98]" disabled={!can('in_review')} onClick={() => p.onTransition('in_review')}>Start review</button>
        <button className="flex-1 py-2.5 rounded-xl text-[13px] font-semibold text-sky-700 bg-sky-50 hover:bg-sky-100 transition-colors disabled:opacity-50 disabled:bg-slate-50 disabled:text-slate-400 active:scale-[0.98]" disabled={!can('approved')} onClick={() => p.onTransition('approved')}>Approve</button>
      </div>
      <button className="w-full py-3.5 mt-1 rounded-xl text-[14px] font-bold shadow-md shadow-sky-500/20 text-white bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 transition-all active:scale-[0.98] disabled:opacity-50 disabled:shadow-none" disabled={p.state !== 'approved'} onClick={p.onOpenSign}>✎ Finalize &amp; sign</button>
      <p className="text-[12px] leading-relaxed text-slate-500 mt-1">Edit &amp; approve the note, then finalize with a signature. Only a finalized note can be exported.</p>

      <div className="flex items-center gap-3 mt-6 mb-1 opacity-80">
        <span className="flex items-center justify-center w-6 h-6 rounded-full bg-sky-100 text-sky-600 text-xs font-bold">3</span>
        <h3 className="text-[11px] font-bold tracking-[1.5px] text-slate-500 uppercase">Export</h3>
      </div>
      <div className="flex flex-wrap gap-2">
        {['json', 'markdown', 'pdf', 'fhir'].map((f) => (
          <button key={f} className="flex-1 py-2 rounded-lg text-[12px] font-semibold text-slate-600 bg-slate-50 border border-slate-200 hover:bg-sky-50 hover:border-sky-200 hover:text-sky-700 transition-all disabled:opacity-40 disabled:hover:bg-slate-50 disabled:hover:border-slate-200 active:scale-[0.98]" disabled={!finalized} onClick={() => p.onExport(f)}>{f.toUpperCase()}</button>
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
