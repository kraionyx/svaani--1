import { useState, type ReactNode } from 'react';
import * as API from '../api';
import { useStore } from '../store';
import { toast } from '../toast';

const STATUS_LABEL: Record<string, string> = {
  draft: 'Draft', previewed: 'Previewed', edited: 'Edited', approved: 'Approved', signed: 'Signed',
};

// Hairline inline icons (inherit currentColor / stroke).
const I = {
  edit: <path d="M4 13.5V16h2.5l7-7L11 6.5l-7 7zM12.5 5l2.5 2.5" />,
  check: <path d="M3.5 8.5l3 3 6-7" />,
  refresh: <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5V5H11" />,
  print: <path d="M5 7V2.5h6V7M5 12H3.5V7h11v5H13M5 10.5h6V15H5z" />,
  doc: <path d="M5 2.5h5L14 6v9.5H5zM10 2.5V6h4" />,
};
const Svg = ({ d }: { d: ReactNode }) => (
  <svg viewBox="0 0 18 18" width="14" height="14" fill="none" stroke="currentColor"
    strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);

export function PrescriptionPreview() {
  const sid = useStore((s) => s.sessionId);
  const [hospitalName, setHospitalName] = useState('');
  const [doc, setDoc] = useState<API.RenderedDocument | null>(null);
  const [editHtml, setEditHtml] = useState('');
  const [editMode, setEditMode] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!sid) return <div className="card muted empty">No active session.</div>;

  async function generate() {
    if (!sid) return;
    setBusy(true);
    try {
      const d = await API.documentPreview(sid, {
        doc_type: 'prescription',
        branding: hospitalName ? { name: hospitalName } : undefined,
      });
      setDoc(d);
      setEditHtml(d.rendered_html);
      setEditMode(false);
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit() {
    if (!doc) return;
    setBusy(true);
    try {
      const d = await API.updateDocument(doc.id, { edited_html: editHtml });
      setDoc(d);
      setEditMode(false);
      toast('Document saved.');
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (!doc) return;
    setBusy(true);
    try {
      const d = await API.approveDocument(doc.id);
      setDoc(d);
      toast('Document approved.');
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  const currentHtml = doc?.edited_html || doc?.rendered_html || '';
  const locked = doc?.status === 'approved' || doc?.status === 'signed';

  function printDoc() {
    // Print from a hidden, same-origin iframe (no pop-up blocker, no deprecated
    // document.write). The Blob URL is revoked once the print dialog is dismissed.
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>OP Note</title></head><body>${currentHtml}</body></html>`;
    const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
    const frame = document.createElement('iframe');
    frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0';
    frame.src = url;
    frame.onload = () => {
      frame.contentWindow?.focus();
      frame.contentWindow?.print();
      setTimeout(() => { frame.remove(); URL.revokeObjectURL(url); }, 1000);
    };
    document.body.appendChild(frame);
  }

  return (
    <div className="card rxx">
      <div className="rxx-head">
        <div className="rxx-headtext">
          <span className="rxx-eyebrow">Hospital document · a faithful scribe</span>
          <h2 className="rxx-title">Prescription <span>/ OP Note</span></h2>
        </div>
        {doc && <span className={`rxx-seal ${doc.status}`}>{STATUS_LABEL[doc.status] || doc.status}</span>}
      </div>

      {!doc ? (
        <div className="rxx-empty">
          <div className="rxx-stack" aria-hidden="true"><i /><i /><i /></div>
          <p className="rxx-empty-lead">Generate the hospital OP note</p>
          <p className="rxx-empty-sub">
            Fills the hospital template with <b>doctor-confirmed</b> clinical content only.
            The AI never authors a prescription — it formats what you confirmed.
          </p>
          <div className="rxx-gen">
            <div className="rxx-field">
              <label className="lbl">Hospital / clinic name <span className="muted">(optional)</span></label>
              <input
                value={hospitalName}
                onChange={(e) => setHospitalName(e.target.value)}
                placeholder="Continental Hospitals"
              />
            </div>
            <button className="btn rxx-gen-btn" disabled={busy} onClick={generate}>
              {busy ? 'Generating…' : 'Generate document'}
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="rxx-toolbar">
            {!editMode && !locked && (
              <button className="rxx-tool" onClick={() => { setEditMode(true); setEditHtml(currentHtml); }}>
                <Svg d={I.edit} />Edit HTML
              </button>
            )}
            {editMode && (
              <>
                <button className="rxx-tool primary" disabled={busy} onClick={saveEdit}>
                  <Svg d={I.check} />{busy ? 'Saving…' : 'Save edits'}
                </button>
                <button className="rxx-tool" onClick={() => setEditMode(false)}>Cancel</button>
              </>
            )}
            {!editMode && !locked && (
              <button className="rxx-tool ok" disabled={busy} onClick={approve}>
                <Svg d={I.check} />{busy ? '…' : 'Approve'}
              </button>
            )}
            {!editMode && (
              <button className="rxx-tool" onClick={printDoc}><Svg d={I.print} />Print / PDF</button>
            )}
            <button className="rxx-tool ghost-r" onClick={() => { setDoc(null); setEditMode(false); }}>
              <Svg d={I.refresh} />{locked ? 'New' : 'Regenerate'}
            </button>
            {locked && doc.approved_by && (
              <span className="rxx-approved-by"><Svg d={I.doc} />Approved by {doc.approved_by}</span>
            )}
          </div>

          {editMode ? (
            <textarea
              className="rxx-code"
              value={editHtml}
              onChange={(e) => setEditHtml(e.target.value)}
              spellCheck={false}
            />
          ) : (
            <div className={`rxx-desk ${locked ? 'sealed' : ''}`}>
              <iframe
                srcDoc={currentHtml}
                className="rxx-paper"
                title="prescription preview"
                sandbox="allow-same-origin"
              />
              {locked && <div className="rxx-wax" aria-hidden="true">✓<span>APPROVED</span></div>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
