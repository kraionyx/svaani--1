import { useState } from 'react';
import * as API from '../api';
import { useStore } from '../store';
import { toast } from '../toast';

const OBJ: { key: string; label: string; cols: [string, string][]; empty: () => any }[] = [
  { key: 'chief_complaints', label: 'Chief complaints', cols: [['symptom', 'Symptom'], ['duration', 'Duration'], ['type', 'Type']], empty: () => ({ symptom: '', duration: '', type: '', provenance: { span_ids: [] } }) },
  { key: 'allergies', label: 'Allergies', cols: [['substance', 'Substance'], ['reaction', 'Reaction']], empty: () => ({ substance: '', reaction: '', provenance: { span_ids: [] } }) },
  { key: 'examination', label: 'Examination', cols: [['region', 'Region'], ['finding', 'Finding'], ['value', 'Value']], empty: () => ({ region: '', finding: '', value: '', provenance: { span_ids: [] } }) },
  { key: 'medications_discussed', label: 'Medications discussed', cols: [['name', 'Drug'], ['dose', 'Dose'], ['route', 'Route'], ['frequency', 'Frequency'], ['duration', 'Duration']], empty: () => ({ name: '', dose: '', route: '', frequency: '', duration: '', verbatim_text: '', provenance: { span_ids: [] } }) },
];
const TEXTLISTS: [string, string][] = [['past_medical_history', 'Past medical history'], ['family_history', 'Family history'], ['investigations', 'Investigations'], ['diagnosis', 'Diagnosis'], ['treatment_plan', 'Treatment plan']];
const SCALARS: [string, string][] = [['history_of_present_illness', 'History of present illness'], ['assessment', 'Assessment'], ['follow_up', 'Follow-up'], ['doctor_notes', 'Doctor notes']];

export function ExtractionEditor() {
  const s = useStore();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<any>(null);
  const [vitals, setVitals] = useState<[string, string][]>([]);
  const [text, setText] = useState<Record<string, string>>({});

  if (!s.extraction) return <div className="card muted">No extraction.</div>;
  const e = s.extraction;
  const editable = !!s.reviewState && ['draft', 'in_review', 'edited'].includes(s.reviewState);
  const mismatched = new Set((s.grounding?.mismatched || []).map((m) => m.split('—')[0].trim()));

  function start() {
    const d = JSON.parse(JSON.stringify(e));
    setDraft(d);
    setVitals(Object.entries(d.vitals || {}) as [string, string][]);
    const tc: Record<string, string> = {};
    TEXTLISTS.forEach(([k]) => { tc[k] = (d[k] || []).map((g: any) => g.text).join('\n'); });
    SCALARS.forEach(([k]) => { tc[k] = d[k]?.text || ''; });
    setText(tc); setEditing(true);
  }
  const mut = (fn: (d: any) => void) => setDraft((prev: any) => { const d = { ...prev }; fn(d); return d; });

  async function save() {
    if (!s.sessionId) return;
    const ex = JSON.parse(JSON.stringify(draft));
    ex.vitals = {}; vitals.forEach(([k, v]) => { if (k.trim()) ex.vitals[k.trim()] = v; });
    TEXTLISTS.forEach(([k]) => { ex[k] = (text[k] || '').split('\n').map((t) => t.trim()).filter(Boolean).map((t) => ({ text: t, provenance: { span_ids: [] } })); });
    SCALARS.forEach(([k]) => { const t = (text[k] || '').trim(); ex[k] = t ? { text: t, provenance: e[k]?.provenance || { span_ids: [] } } : null; });
    OBJ.forEach(({ key, cols }) => { ex[key] = (ex[key] || []).filter((o: any) => cols.some(([c]) => String(o[c] ?? '').trim())); });
    try {
      const r: any = await API.saveExtraction(s.sessionId, ex);
      s.set({ extraction: r.extraction, note: r.note, grounding: r.grounding, reviewState: r.state });
      setEditing(false);
      const n = (r.grounding.mismatched || []).length;
      toast(`Extraction saved · note updated${n ? ` · ⚠ ${n} not in transcript` : ''}.`);
    } catch (err: any) { toast('save failed: ' + err.message, true); }
  }

  if (editing && draft) {
    return (
      <div className="card">
        <h2>Edit clinical extraction</h2>
        <div className="editbar">
          <button className="btn sm" onClick={save}>Save changes</button>
          <button className="btn ghost sm" onClick={() => setEditing(false)}>Cancel</button>
          <span className="kv">Saving re-renders the note and re-verifies against the transcript.</span>
        </div>
        {OBJ.map(({ key, label, cols, empty }) => (
          <div key={key}>
            <p><b>{label}</b></p>
            <table className="edit-tbl"><thead><tr>{cols.map(([, h]) => <th key={h}>{h}</th>)}<th /></tr></thead>
              <tbody>{(draft[key] || []).map((o: any, i: number) => (
                <tr key={i}>
                  {cols.map(([c, h]) => <td key={c}><input value={o[c] ?? ''} placeholder={h}
                    onChange={(ev) => mut((d) => { d[key] = [...d[key]]; d[key][i] = { ...d[key][i], [c]: ev.target.value }; })} /></td>)}
                  <td><button className="x" onClick={() => mut((d) => { d[key] = d[key].filter((_: any, j: number) => j !== i); })}>✕</button></td>
                </tr>))}
              </tbody>
            </table>
            <button className="btn ghost sm" onClick={() => mut((d) => { d[key] = [...(d[key] || []), empty()]; })}>+ add row</button>
          </div>
        ))}
        <p><b>Vitals</b></p>
        <table className="edit-tbl"><thead><tr><th>Name</th><th>Value</th><th /></tr></thead>
          <tbody>{vitals.map(([k, v], i) => (
            <tr key={i}>
              <td><input value={k} placeholder="name" onChange={(ev) => setVitals((p) => p.map((row, j) => j === i ? [ev.target.value, row[1]] : row))} /></td>
              <td><input value={v} placeholder="value" onChange={(ev) => setVitals((p) => p.map((row, j) => j === i ? [row[0], ev.target.value] : row))} /></td>
              <td><button className="x" onClick={() => setVitals((p) => p.filter((_, j) => j !== i))}>✕</button></td>
            </tr>))}
          </tbody>
        </table>
        <button className="btn ghost sm" onClick={() => setVitals((p) => [...p, ['', '']])}>+ add vital</button>
        {SCALARS.map(([k, label]) => (
          <div key={k}><p><b>{label}</b></p>
            <textarea value={text[k] || ''} onChange={(ev) => setText((t) => ({ ...t, [k]: ev.target.value }))} /></div>
        ))}
        {TEXTLISTS.map(([k, label]) => (
          <div key={k}><p><b>{label}</b> <span className="kv">(one per line)</span></p>
            <textarea value={text[k] || ''} onChange={(ev) => setText((t) => ({ ...t, [k]: ev.target.value }))} /></div>
        ))}
      </div>
    );
  }

  const exByRegion: Record<string, string[]> = {};
  (e.examination || []).forEach((f) => { (exByRegion[f.region] = exByRegion[f.region] || []).push(`${f.finding}: ${f.value}`); });

  return (
    <div className="card">
      <h2>Clinical extraction (grounded)</h2>
      {editable && <div className="editbar"><button className="btn ghost sm" onClick={start}>✎ Edit extraction</button>
        <span className="kv">Edits re-render the note and re-check it against the transcript.</span></div>}
      {e.history_of_present_illness?.text && <><p><b>History of present illness</b></p><p>{e.history_of_present_illness.text}</p></>}
      <p><b>Chief complaints</b></p>
      <ul>{e.chief_complaints?.length ? e.chief_complaints.map((c, i) => <li key={i}>{c.symptom}{c.duration ? ` (${c.duration})` : ''}{c.type ? ` [${c.type}]` : ''}</li>) : <li className="muted">none</li>}</ul>
      <p><b>Allergies</b></p>
      <ul>{e.allergies?.length ? e.allergies.map((a, i) => <li key={i}>{a.substance}{a.reaction ? ` — ${a.reaction}` : ''}</li>) : <li className="muted">none</li>}</ul>
      <p><b>Examination</b></p>
      <ul>{Object.keys(exByRegion).length ? Object.entries(exByRegion).map(([r, v]) => <li key={r}><b>{r}</b>: {v.join(', ')}</li>) : <li className="muted">none</li>}</ul>
      {Object.keys(e.vitals || {}).length > 0 && <><p><b>Vitals</b></p><ul>{Object.entries(e.vitals).map(([k, v]) => <li key={k}><b>{k}</b>: {v}</li>)}</ul></>}
      <p><b>Medications discussed</b></p>
      <ul>{e.medications_discussed?.length ? e.medications_discussed.map((m, i) => {
        const flagged = mismatched.has(`medication:${m.name}${m.dose ? ' ' + m.dose : ''}`);
        return <li key={i}>{m.name} {m.dose || ''} {m.frequency || ''} <span className={`sev ${flagged ? 'high' : 'moderate'}`} style={{ fontSize: 9 }}>{flagged ? '⚠ not in transcript' : 'verify'} · non-authoritative</span></li>;
      }) : <li className="muted">none discussed</li>}</ul>
    </div>
  );
}
