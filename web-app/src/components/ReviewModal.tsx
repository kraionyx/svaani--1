import { useState } from 'react';
import type { ReviewState } from '../api';

export function ReviewModal({
  isOpen,
  onClose,
  sessionId,
  reviewState,
  onTransition,
  onExport
}: {
  isOpen: boolean;
  onClose: () => void;
  sessionId: string;
  reviewState: ReviewState | null;
  onTransition: (state: string, extra?: any) => Promise<any>;
  onExport: (fmt: string) => void;
}) {
  const [step, setStep] = useState<'review' | 'export'>('review');
  const [name, setName] = useState('');
  
  if (!isOpen) return null;

  async function handleFinalize() {
    if (!name.trim()) return;
    try {
      await onTransition('finalized', { signed_by_name: name.trim() });
      setStep('export');
    } catch {
      // Error handled upstream
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 backdrop-blur-sm animate-in fade-in duration-200" onClick={onClose}>
      <div 
        className="bg-white rounded-2xl shadow-2xl w-[480px] max-w-[90vw] overflow-hidden flex flex-col animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <h2 className="text-lg font-semibold text-slate-800">
            {step === 'review' ? 'Review & Sign-off' : 'Export Consultation'}
          </h2>
          <button 
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-slate-200 text-slate-500 transition-colors"
          >
            ✕
          </button>
        </div>

        <div className="p-6">
          {step === 'review' ? (
            <div className="flex flex-col gap-5">
              <div className="bg-sky-50/50 rounded-xl p-4 border border-sky-100">
                <p className="text-sm text-slate-600 mb-3 leading-relaxed">
                  Please review the consultation note. Once approved, you can sign off to finalize it.
                  A finalized note cannot be further edited and is ready for export.
                </p>
                <div className="flex gap-2">
                   <button 
                     className="flex-1 py-2 rounded-lg text-[13px] font-semibold text-sky-700 bg-white border border-sky-200 hover:bg-sky-50 transition-colors disabled:opacity-50" 
                     disabled={reviewState === 'in_review'} 
                     onClick={() => onTransition('in_review')}
                   >
                     Mark In-Review
                   </button>
                   <button 
                     className="flex-1 py-2 rounded-lg text-[13px] font-semibold text-sky-700 bg-white border border-sky-200 hover:bg-sky-50 transition-colors disabled:opacity-50" 
                     disabled={reviewState === 'approved'} 
                     onClick={() => onTransition('approved')}
                   >
                     Approve Note
                   </button>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-sm font-semibold text-slate-700">Signing Clinician Name</label>
                <input 
                  value={name} 
                  onChange={(e) => setName(e.target.value)} 
                  placeholder="e.g. Dr. Smith" 
                  className="w-full px-4 py-2.5 rounded-xl border border-slate-300 focus:border-sky-500 focus:ring-2 focus:ring-sky-100 outline-none transition-all"
                  autoFocus 
                />
              </div>

              <button 
                className="w-full py-3.5 mt-2 rounded-xl text-[14px] font-bold shadow-md shadow-sky-500/20 text-white bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 transition-all active:scale-[0.98] disabled:opacity-50 disabled:shadow-none" 
                disabled={!name.trim()} 
                onClick={handleFinalize}
              >
                ✎ Finalize & Sign
              </button>
            </div>
          ) : (
            <div className="flex flex-col gap-6">
              <div className="flex flex-col items-center justify-center py-4">
                <div className="w-16 h-16 bg-green-100 text-green-600 rounded-full flex items-center justify-center mb-4">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
                </div>
                <h3 className="text-lg font-bold text-slate-800">Successfully Finalized</h3>
                <p className="text-sm text-slate-500 mt-1 text-center">
                  This consultation has been signed off by {name}. It is now ready to be exported or pushed to the EHR.
                </p>
              </div>

              <div className="flex flex-col gap-3">
                <label className="text-xs font-bold tracking-wider text-slate-400 uppercase">Standard Export</label>
                <div className="flex bg-slate-100 rounded-xl p-1 relative">
                   <select 
                     className="w-full bg-white px-4 py-3 rounded-lg text-sm font-medium border border-slate-200 shadow-sm outline-none appearance-none cursor-pointer"
                     onChange={(e) => {
                       if (e.target.value) {
                         onExport(e.target.value);
                         e.target.value = '';
                       }
                     }}
                     defaultValue=""
                   >
                     <option value="" disabled>Select format to download...</option>
                     <option value="pdf">PDF Document (.pdf)</option>
                     <option value="markdown">Markdown (.md)</option>
                     <option value="json">Raw JSON (.json)</option>
                   </select>
                   <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
                     <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                   </div>
                </div>
              </div>

              <div className="flex flex-col gap-3">
                <label className="text-xs font-bold tracking-wider text-slate-400 uppercase">EHR Integration</label>
                <button 
                  className="w-full py-3.5 rounded-xl text-[14px] font-bold text-slate-700 bg-white border-2 border-indigo-100 hover:border-indigo-300 hover:bg-indigo-50 transition-all flex items-center justify-center gap-2"
                  onClick={() => onExport('fhir')}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v20"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
                  Export as FHIR Bundle
                </button>
              </div>
              
              <button 
                className="w-full py-2.5 rounded-xl text-[13px] font-semibold text-slate-500 hover:bg-slate-100 transition-colors mt-2" 
                onClick={onClose}
              >
                Close Window
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
