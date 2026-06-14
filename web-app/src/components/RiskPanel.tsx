import { useState } from 'react';
import * as API from '../api';
import { useStore } from '../store';
import { toast } from '../toast';

const TYPES = ['red_flag_symptom', 'allergy_mentioned', 'medication_mentioned', 'dosage_mentioned', 'abnormal_vital', 'low_stt_confidence', 'other'];
const SEVS = ['info', 'low', 'moderate', 'high', 'critical'];

export function RiskPanel() {
  const s = useStore();
  const [editing, setEditing] = useState(false);
  const [rows, setRows] = useState<API.RiskMarker[]>([]);

  if (!s.risk) return <div className="card muted">No risk assessment.</div>;
  const editable = !!s.reviewState && ['draft', 'in_review', 'edited'].includes(s.reviewState);
  const pct = Math.round((s.risk.score || 0) * 100);

  const start = () => { setRows(JSON.parse(JSON.stringify(s.risk!.markers))); setEditing(true); };
  const upd = (i: number, k: keyof API.RiskMarker, v: string) => setRows((r) => r.map((m, j) => j === i ? { ...m, [k]: v } : m));
  const add = () => setRows((r) => [...r, { type: 'other', severity: 'info', message: '', evidence_text: '', evidence_span_ids: [] }]);
  const rm = (i: number) => setRows((r) => r.filter((_, j) => j !== i));

  async function save() {
    if (!s.sessionId) return;
    const markers = rows.filter((m) => m.message.trim());
    try { const r: any = await API.saveRisk(s.sessionId, markers); s.set({ risk: r.risk, reviewState: r.state }); setEditing(false); toast('Risk markers saved.'); }
    catch (e: any) { toast('save failed: ' + e.message, true); }
  }

  if (editing) {
    return (
      <div className="card">
        <h2>Edit risk markers</h2>
        <div className="editbar">
          <button className="btn sm" onClick={save}>Save changes</button>
          <button className="btn ghost sm" onClick={() => setEditing(false)}>Cancel</button>
          <button className="btn ghost sm" onClick={add}>+ add marker</button>
        </div>
        {rows.map((m, i) => (
          <div className="marker edit" key={i}>
            <select value={m.severity} onChange={(e) => upd(i, 'severity', e.target.value)}>{SEVS.map((x) => <option key={x}>{x}</option>)}</select>
            <div style={{ flex: 1 }}>
              <select value={m.type} onChange={(e) => upd(i, 'type', e.target.value)} style={{ marginBottom: 6 }}>{TYPES.map((x) => <option key={x}>{x}</option>)}</select>
              <input value={m.message} placeholder="marker message" onChange={(e) => upd(i, 'message', e.target.value)} />
              <input value={m.evidence_text || ''} placeholder="quoted evidence" style={{ marginTop: 6 }} onChange={(e) => upd(i, 'evidence_text', e.target.value)} />
            </div>
            <button className="x" onClick={() => rm(i)}>✕</button>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Risk markers · attention score {pct}%</h2>
      <div className="gauge"><div style={{ width: `${pct}%` }} /></div>
      {editable && <div className="editbar"><button className="btn ghost sm" onClick={start}>✎ Edit risk markers</button></div>}
      {(s.risk.markers || []).map((m, i) => (
        <div className="marker" key={i}>
          <span className={`sev ${m.severity}`}>{m.severity}</span>
          <div>
            <b>{m.type.replace(/_/g, ' ')}</b>
            <div>{m.message}</div>
            {m.evidence_text && <blockquote className="evidence">“{m.evidence_text}”</blockquote>}
            <div className="kv">evidence: {(m.evidence_span_ids || []).join(', ') || '—'} · non-authoritative</div>
          </div>
        </div>
      ))}
      {!s.risk.markers?.length && <p className="muted">No risk markers.</p>}
      {s.risk.disclaimer && <div className="disclaimer">{s.risk.disclaimer}</div>}
    </div>
  );
}
