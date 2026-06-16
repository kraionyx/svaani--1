import { useEffect, useRef, useState } from 'react';
import * as API from '../api';
import { useStore } from '../store';
import { toast } from '../toast';

type Target = 'note' | 'extraction' | 'risk';

interface Preview { instruction: string; changes: API.AiEditChange[]; proposed?: any; }

const PLACEHOLDER: Record<Target, string> = {
  note: 'e.g. "Move diabetes to past medical history" or "Summarise the chief complaint"',
  extraction: 'e.g. "Move hypertension into past medical history" or "Merge the two cough complaints"',
  risk: 'e.g. "Lower the fever marker to moderate" or "Remove the duplicate allergy marker"',
};

/** A small robot icon that opens a popover prompt box to AI-edit the current tab.
 *  Note edits reuse the preview/apply/undo backend; Extraction & Risk use their own
 *  preview→apply routes. Nothing is applied until the doctor approves the preview. */
export function AiBot({ target, className = '' }: { target: Target; className?: string }) {
  const s = useStore();
  const sid = s.sessionId;
  const [open, setOpen] = useState(false);
  const [instruction, setInstruction] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [open]);

  function close() { setOpen(false); setPreview(null); setInstruction(''); }

  function handleErr(e: any) {
    const msg = e?.message || '';
    if (msg.includes('503') || msg.toLowerCase().includes('unavailable') || msg.toLowerCase().includes('disabled'))
      toast('AI editor requires a live Vertex API key (LLM currently disabled).', true);
    else toast(msg, true);
  }

  async function doPreview() {
    if (!sid || !instruction.trim()) return;
    setBusy(true);
    try {
      const body = { instruction: instruction.trim() };
      const p = target === 'note' ? await API.aiEditPreview(sid, body)
        : target === 'extraction' ? await API.aiEditExtractionPreview(sid, body)
        : await API.aiEditRiskPreview(sid, body);
      setPreview(p as Preview);
    } catch (e) { handleErr(e); } finally { setBusy(false); }
  }

  async function applyChanges() {
    if (!sid || !preview) return;
    setBusy(true);
    try {
      if (target === 'note') {
        const changes = preview.changes.map((c) => ({ section_id: c.section_id, content_text: c.after ?? c.content_text ?? '' }));
        const res = await API.aiEditApply(sid, { instruction: preview.instruction, changes });
        s.set({ note: res.note, reviewState: res.state as any });
      } else if (target === 'extraction') {
        const res = await API.aiEditExtractionApply(sid, { instruction: preview.instruction, proposed: preview.proposed });
        s.set({ extraction: res.extraction, note: res.note, grounding: res.grounding, reviewState: res.state as any });
      } else {
        const res = await API.aiEditRiskApply(sid, { instruction: preview.instruction, proposed: preview.proposed });
        s.set({ risk: res.risk, reviewState: res.state as any });
      }
      toast('AI edit applied.');
      close();
    } catch (e) { handleErr(e); } finally { setBusy(false); }
  }

  async function doUndoRedo(kind: 'undo' | 'redo') {
    if (!sid) return;
    setBusy(true);
    try {
      const res = kind === 'undo' ? await API.aiEditUndo(sid) : await API.aiEditRedo(sid);
      s.set({ note: res.note, reviewState: res.state as any });
      toast(`Edit ${kind === 'undo' ? 'undone' : 're-applied'}.`);
    } catch (e: any) {
      const msg = e?.message || '';
      toast(msg.includes('409') ? `Nothing to ${kind}.` : msg, true);
    } finally { setBusy(false); }
  }

  if (!sid) return null;

  return (
    <div className={`ai-bot-wrap ${className}`} ref={wrapRef}>
      <button
        type="button"
        className={`ai-bot ${open ? 'on' : ''}`}
        title="Ask AI to edit this tab"
        aria-label="AI edit this tab"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
          strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="4" y="8" width="16" height="11" rx="3" />
          <path d="M12 8V4.5" />
          <circle cx="12" cy="3" r="1.4" fill="currentColor" stroke="none" />
          <circle cx="9" cy="13.2" r="1.25" fill="currentColor" stroke="none" />
          <circle cx="15" cy="13.2" r="1.25" fill="currentColor" stroke="none" />
          <path d="M2 12.5v3M22 12.5v3" />
        </svg>
      </button>

      {open && (
        <div className="ai-pop" role="dialog" aria-label={`AI edit ${target}`}>
          <div className="ai-pop-h">
            <span className="ai-pop-title">AI edit · {target}</span>
            <button type="button" className="ai-pop-x" onClick={close} aria-label="Close">✕</button>
          </div>
          <p className="hint" style={{ marginTop: 0 }}>
            Describe an edit in plain language. It previews first — nothing applies until you approve.
            It only reorganises or rephrases what's already here; it never adds new clinical facts.
          </p>
          <textarea
            value={instruction}
            autoFocus
            onChange={(e) => setInstruction(e.target.value)}
            placeholder={PLACEHOLDER[target]}
            rows={3}
          />
          <div className="row">
            <button className="btn sm" disabled={busy || !instruction.trim()} onClick={doPreview}>
              {busy && !preview ? 'Previewing…' : 'Preview'}
            </button>
            {target === 'note' && (
              <>
                <button className="btn ghost sm" disabled={busy} onClick={() => doUndoRedo('undo')}>↶ Undo</button>
                <button className="btn ghost sm" disabled={busy} onClick={() => doUndoRedo('redo')}>↷ Redo</button>
              </>
            )}
          </div>

          {preview && (
            <div className="ai-pop-preview">
              {preview.changes.length === 0 ? (
                <div className="muted" style={{ fontSize: 12 }}>No changes proposed for that instruction.</div>
              ) : (
                <>
                  {preview.changes.map((c, i) => (
                    <div key={i} className="ai-proposal">
                      <h4>{c.section_id}</h4>
                      <div className="ai-diff">
                        <div><div className="lbl">Before</div><div className="ai-before">{c.before || '(empty)'}</div></div>
                        <div><div className="lbl">After</div><div className="ai-after">{c.after || '(empty)'}</div></div>
                      </div>
                    </div>
                  ))}
                  <div className="row">
                    <button className="btn sm" disabled={busy} onClick={applyChanges}>{busy ? 'Applying…' : 'Apply'}</button>
                    <button className="btn ghost sm" onClick={() => setPreview(null)}>Discard</button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
