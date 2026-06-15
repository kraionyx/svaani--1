import { useState, useEffect } from 'react';
import * as API from '../api';
import { useStore } from '../store';
import { toast } from '../toast';

const ROLES = ['doctor', 'patient', 'caregiver', 'nurse', 'translator', 'unknown'];
const RELS = ['self', 'parent', 'spouse', 'child', 'sibling', 'guardian', 'caregiver', 'translator', 'clinician', 'nurse', 'other', 'unknown'];

export function SpeakerTimeline() {
  const sid = useStore((s) => s.sessionId);
  const [profile, setProfile] = useState<API.ConversationProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [edits, setEdits] = useState<Record<string, { role?: string; relationship?: string }>>({});
  const [refPat, setRefPat] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!sid) return;
    setLoading(true);
    setEdits({});
    API.getProfile(sid)
      .then((p) => { setProfile(p); setRefPat(p.referenced_patient || ''); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [sid]);

  if (!sid) return <div className="card muted empty">No active session.</div>;
  if (loading) return <div className="card muted empty">Loading…</div>;
  if (!profile) return <div className="card muted empty">No conversation profile yet — run a consultation first.</div>;

  const isDirty = Object.keys(edits).length > 0 || refPat !== (profile.referenced_patient || '');
  const bandColor = { high: 'var(--ok)', moderate: 'var(--moderate)', low: 'var(--high)' }[profile.confidence_band];

  async function save() {
    if (!sid) return;
    setBusy(true);
    try {
      const corrections = Object.entries(edits).map(([label, c]) => ({ speaker_label: label, ...c }));
      const res = await API.patchSpeakers(sid, { corrections, referenced_patient: refPat || undefined });
      setProfile((p) => p ? { ...p, referenced_patient: res.referenced_patient, speakers: res.speakers } : p);
      setEdits({});
      toast('Speaker roles updated — note re-rendered.');
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="note-head">
        <h2 style={{ margin: 0 }}>Speaker timeline</h2>
        <span className="badge">{profile.kind.replace(/_/g, ' ')}</span>
        <span style={{ color: bandColor, fontSize: 12, fontWeight: 700 }}>
          {profile.confidence_band.toUpperCase()} confidence ({profile.confidence_pct}%)
        </span>
        {profile.is_complex && (
          <span className="badge" style={{ background: 'var(--moderate)', color: '#fff' }}>
            Complex {Math.round(profile.complexity_score * 100)}%
          </span>
        )}
      </div>

      <label className="lbl">Referenced patient (who the symptoms are about)</label>
      <input
        value={refPat}
        onChange={(e) => setRefPat(e.target.value)}
        placeholder="e.g. son, patient, father"
        style={{ width: '100%', marginBottom: 14 }}
      />

      <div style={{ overflowX: 'auto' }}>
        <table className="edit-tbl" style={{ minWidth: 480 }}>
          <thead>
            <tr>
              <th>Speaker</th><th>Role</th><th>Relationship</th><th>Subject / conf</th>
            </tr>
          </thead>
          <tbody>
            {profile.speakers.map((sp) => (
              <tr key={sp.speaker_label}>
                <td><span style={{ fontWeight: 700, fontSize: 11, textTransform: 'uppercase', color: 'var(--accent-strong)' }}>{sp.speaker_label}</span></td>
                <td>
                  <select
                    value={edits[sp.speaker_label]?.role ?? sp.role}
                    onChange={(e) => setEdits((d) => ({ ...d, [sp.speaker_label]: { ...d[sp.speaker_label], role: e.target.value } }))}
                  >
                    {ROLES.map((r) => <option key={r}>{r}</option>)}
                  </select>
                </td>
                <td>
                  <select
                    value={edits[sp.speaker_label]?.relationship ?? sp.relationship}
                    onChange={(e) => setEdits((d) => ({ ...d, [sp.speaker_label]: { ...d[sp.speaker_label], relationship: e.target.value } }))}
                  >
                    {RELS.map((r) => <option key={r}>{r}</option>)}
                  </select>
                </td>
                <td className="kv">
                  {sp.subject_patient && <span>→ {sp.subject_patient} </span>}
                  <span className="muted">({Math.round(sp.confidence * 100)}%)</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(profile.confidence_reasons.length > 0 || profile.complexity_signals.length > 0) && (
        <div className="disclaimer" style={{ marginTop: 12 }}>
          {[...profile.confidence_reasons, ...profile.complexity_signals].join(' · ')}
        </div>
      )}

      <div className="row" style={{ marginTop: 12 }}>
        <button className="btn sm" disabled={!isDirty || busy} onClick={save}>
          {busy ? 'Saving…' : 'Apply corrections & re-render note'}
        </button>
        {!isDirty && <span className="kv muted" style={{ lineHeight: '32px' }}>No changes</span>}
      </div>
    </div>
  );
}
