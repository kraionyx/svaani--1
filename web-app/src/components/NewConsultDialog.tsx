// Confirmation shown when "New Consultation" would interrupt an active or unfinished consult.
// Driven entirely by props from the Scribe workspace (which owns the live socket + mic and the
// actual start/stop/discard handlers). When `mode` is null nothing renders.
import { useEffect } from 'react';

export type NewConsultMode = null | 'unfinished' | 'recording' | 'processing';

interface Props {
  mode: NewConsultMode;
  stateLabel?: string;           // human label for the current consult's state (e.g. "Draft")
  onClose: () => void;           // keep the current consultation
  onStartFresh: () => void;      // start a brand-new consult (nothing persisted is lost)
  onSaveDraftAndNew: () => void; // recording → stop & finalize into a draft, then start new
  onDiscardAndNew: () => void;   // recording → discard the recording, then start new
}

interface ActionDef {
  label: string;
  onClick: () => void;
  variant: 'primary' | 'secondary' | 'danger';
}

export function NewConsultDialog(p: Props) {
  useEffect(() => {
    if (!p.mode) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') p.onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [p.mode, p.onClose]);

  if (!p.mode) return null;

  let title: string;
  let message: string;
  let actions: ActionDef[];

  if (p.mode === 'recording') {
    title = 'Recording in progress';
    message = 'You have a consultation that is still recording. Starting a new one will interrupt your current workflow.';
    actions = [
      { label: 'Continue recording', onClick: p.onClose, variant: 'secondary' },
      { label: 'Save as draft & start new', onClick: p.onSaveDraftAndNew, variant: 'primary' },
      { label: 'Discard & start new', onClick: p.onDiscardAndNew, variant: 'danger' },
    ];
  } else if (p.mode === 'processing') {
    title = 'Consultation is processing';
    message = 'Transcription and note generation are still running. They will finish in the background and the draft will appear in your Recents — you don’t need to wait.';
    actions = [
      { label: 'Keep waiting', onClick: p.onClose, variant: 'secondary' },
      { label: 'Start new in background', onClick: p.onStartFresh, variant: 'primary' },
    ];
  } else {
    // unfinished: an open draft / in-review consult — already saved server-side.
    title = 'You have an unfinished consultation';
    message = `Your current consultation${p.stateLabel ? ` (${p.stateLabel})` : ''} is saved and will stay in your Recents — you can return to it anytime. Start a new consultation?`;
    actions = [
      { label: 'Return to current', onClick: p.onClose, variant: 'secondary' },
      { label: 'Start new consultation', onClick: p.onStartFresh, variant: 'primary' },
    ];
  }

  const cls = (v: ActionDef['variant']) =>
    v === 'primary'
      ? 'bg-sky-600 hover:bg-sky-700 text-white shadow-sm shadow-sky-500/20'
      : v === 'danger'
      ? 'bg-white border border-red-200 text-red-600 hover:bg-red-50'
      : 'bg-slate-100 hover:bg-slate-200 text-slate-700';

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/40 backdrop-blur-sm animate-in fade-in duration-150"
      onClick={p.onClose}
      role="presentation"
    >
      <div
        className="bg-white rounded-2xl shadow-xl border border-slate-200 max-w-md w-full mx-4 p-6 animate-in zoom-in-95 duration-150"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center shrink-0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>
          </div>
          <div>
            <h2 className="text-[16px] font-semibold text-slate-800">{title}</h2>
            <p className="text-[13px] text-slate-500 mt-1 leading-relaxed">{message}</p>
          </div>
        </div>
        <div className="flex flex-col gap-2 mt-5">
          {actions.map((a) => (
            <button
              key={a.label}
              onClick={a.onClick}
              className={`w-full py-2.5 rounded-xl text-[14px] font-semibold transition-all active:scale-[0.98] ${cls(a.variant)}`}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
