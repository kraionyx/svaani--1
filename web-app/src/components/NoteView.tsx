import { useState } from 'react';
import * as API from '../api';
import { useStore } from '../store';
import { toast } from '../toast';
import { AiBot } from './AiBot';

export function NoteView() {
  const s = useStore();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});

  const editable = !!s.reviewState && ['draft', 'in_review', 'edited'].includes(s.reviewState);

  // While the note is still streaming in (no final note yet), show the live sections.
  if (!s.note && s.liveNoteOrder.length) {
    return (
      <div className="card">
        <h2>Consultation note <span className="kv">· generating…</span></h2>
        {s.liveNoteOrder.map((id) => {
          const sec = s.liveNote[id];
          return (
            <div className="note-sec" key={id}>
              <h4>{sec.label}{!sec.done && <span className="caret">▍</span>}</h4>
              <div className="body">{sec.text}</div>
            </div>
          );
        })}
      </div>
    );
  }

  if (!s.note) return <div className="card muted">No note yet.</div>;
  const secs = [...s.note.sections].sort((a, b) => a.order - b.order);

  async function save() {
    if (!s.sessionId || !s.note) return;
    const sections = s.note.sections.map((x) => ({ section_id: x.section_id, content_text: draft[x.section_id] ?? x.content_text }));
    try {
      const r: any = await API.saveNote(s.sessionId, sections);
      s.set({ note: r.note, reviewState: r.state }); setEditing(false);
      toast('Note saved · ' + r.state.replace('_', ' '));
    } catch (e: any) { toast('save failed: ' + e.message, true); }
  }

  return (
    <div className="card">
      <div className="note-head">
        <h2>Consultation note</h2>
        <span className={`badge state-${s.reviewState}`}>{s.reviewState?.replace('_', ' ')}</span>
        <span className="kv">{s.note.template_id}@{s.note.template_version}</span>
        {editable && <AiBot target="note" className="push" />}
      </div>
      {editable && (
        <div className="editbar">
          {editing
            ? (<><button className="btn sm" onClick={save}>Save changes</button>
              <button className="btn ghost sm" onClick={() => setEditing(false)}>Cancel</button></>)
            : (<button className="btn ghost sm" onClick={() => { setDraft({}); setEditing(true); }}>✎ Edit note</button>)}
        </div>
      )}
      {secs.map((sec) => (
        <div className="note-sec" key={sec.section_id}>
          <h4>{sec.label}</h4>
          {editing
            ? <textarea defaultValue={sec.content_text} onChange={(e) => setDraft((d) => ({ ...d, [sec.section_id]: e.target.value }))} />
            : <div className={`body ${sec.empty ? 'empty' : ''}`}>{sec.empty ? 'Not discussed.' : sec.content_text}</div>}
        </div>
      ))}
    </div>
  );
}
