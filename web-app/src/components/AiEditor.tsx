import { useState, useEffect } from 'react';
import * as API from '../api';
import { useStore } from '../store';
import { toast } from '../toast';

export function AiEditor() {
  const s = useStore();
  const sid = s.sessionId;
  const [instruction, setInstruction] = useState('');
  const [preview, setPreview] = useState<{ instruction: string; changes: API.AiEditChange[] } | null>(null);
  const [history, setHistory] = useState<API.EditEntry[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!sid) return;
    API.getEdits(sid).then(setHistory).catch(() => {});
  }, [sid]);

  if (!sid) return <div className="card muted empty">No active session.</div>;
  if (!s.note) return <div className="card muted empty">No note yet — run a consultation first.</div>;

  async function doPreview() {
    if (!sid || !instruction.trim()) return;
    setBusy(true);
    try {
      const p = await API.aiEditPreview(sid, { instruction: instruction.trim() });
      setPreview(p);
    } catch (e: any) {
      const msg = e.message || '';
      if (msg.includes('503') || msg.toLowerCase().includes('unavailable') || msg.toLowerCase().includes('disabled')) {
        toast('AI editor requires a live Vertex API key (LLM currently disabled).', true);
      } else {
        toast(msg, true);
      }
    } finally {
      setBusy(false);
    }
  }

  async function applyChanges() {
    if (!sid || !preview) return;
    setBusy(true);
    try {
      const changes = preview.changes.map((c) => ({
        section_id: c.section_id,
        content_text: c.after ?? c.content_text ?? '',
      }));
      const res = await API.aiEditApply(sid, { instruction: preview.instruction, changes });
      s.set({ note: res.note, reviewState: res.state as any });
      const updated = await API.getEdits(sid);
      setHistory(updated);
      setPreview(null);
      setInstruction('');
      toast('AI edit applied — note updated.');
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2>AI consultation editor</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Describe an edit in plain language. The AI previews changes — nothing applies until you approve.
        It cannot add new clinical facts; it only reorganises or rephrases what was said.
      </p>

      <label className="lbl">Edit instruction</label>
      <textarea
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        placeholder={`e.g. "Move diabetes to past medical history" or "Summarise chief complaint more concisely"`}
        rows={3}
      />
      <button
        className="btn sm"
        style={{ marginTop: 8 }}
        disabled={busy || !instruction.trim()}
        onClick={doPreview}
      >
        {busy && !preview ? 'Previewing…' : 'Preview changes'}
      </button>

      {preview && (
        <div style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 13, margin: '0 0 10px' }}>Proposed changes — review before applying</h3>
          {preview.changes.map((c, i) => (
            <div key={i} className="ai-proposal">
              <h4>{c.section_id}</h4>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 12 }}>
                <div>
                  <div className="lbl">Before</div>
                  <div style={{ color: 'var(--muted)', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{c.before || '(empty)'}</div>
                </div>
                <div>
                  <div className="lbl">After</div>
                  <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>{c.after || '(empty)'}</div>
                </div>
              </div>
            </div>
          ))}
          <div className="row">
            <button className="btn sm" disabled={busy} onClick={applyChanges}>
              {busy ? 'Applying…' : 'Apply all changes'}
            </button>
            <button className="btn ghost sm" onClick={() => setPreview(null)}>Discard</button>
          </div>
        </div>
      )}

      {history.length > 0 && (
        <div style={{ marginTop: 20, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
          <h3 style={{ fontSize: 13, margin: '0 0 8px' }}>Edit history ({history.length})</h3>
          {[...history].reverse().map((e, i) => (
            <div key={i} className="admin-row" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', gap: 8, width: '100%', alignItems: 'center' }}>
                <span className="stage-pill">{e.section_id}</span>
                <span style={{ flex: 1, fontSize: 12 }}>{e.instruction}</span>
                <span className="adm-meta">#{e.seq}</span>
              </div>
              {e.after && (
                <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                  {e.after.slice(0, 140)}{e.after.length > 140 ? '…' : ''}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
