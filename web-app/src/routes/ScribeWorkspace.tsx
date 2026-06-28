// The live consultation console — extracted verbatim from the former monolithic App.tsx
// when routing was introduced. The app chrome (top bar, sidebar, breadcrumbs, theme studio,
// toasts) now lives in AppLayout; this route owns only the consult workspace + its logic.
import { useEffect, useRef, useState } from 'react';
import * as API from '../api';
import { useAuth } from '../auth';
import { useStore } from '../store';
import { toast } from '../toast';
import { ConsultSocket } from '../ws';
import { startMic, micSupported, type MicHandle } from '../audio';
import { Recorder } from '../components/Recorder';
import { Tabs } from '../components/Tabs';
import { NoteView } from '../components/NoteView';
import { RiskPanel } from '../components/RiskPanel';
import { ExtractionEditor } from '../components/ExtractionEditor';
import { GroundingPanel } from '../components/GroundingPanel';
import { TranscriptView } from '../components/TranscriptView';
import { NoticeBanner } from '../components/NoticeBanner';
import { SpeakerTimeline } from '../components/SpeakerTimeline';
import { ReviewModal } from '../components/ReviewModal';
import { PrescriptionPreview } from '../components/PrescriptionPreview';
import { AdminDashboard } from '../components/AdminDashboard';


export function ScribeWorkspace() {
  const s = useStore();
  const { session } = useAuth();
  const [signOpen, setSignOpen] = useState(false);
  const sockRef = useRef<ConsultSocket | null>(null);
  const micRef = useRef<MicHandle | null>(null);
  useEffect(() => {
    s.loadHistory();
  }, []);

  // ── Streaming consult via WebSocket ────────────────────────────────────────
  async function record() {
    if (s.recording) return stopRecord();
    if (!micSupported()) { toast('Microphone needs https or localhost.', true); return; }
    s.resetSession();
    const riskAcc: API.RiskMarker[] = [];
    const sock = new ConsultSocket(); sockRef.current = sock;
    try {
      const sid = await sock.connect(s.templateId, {
        onStage: (stage, streaming) => s.set({ stage, streaming: !!streaming, reviewState: stage === 'listening' ? 'listening' : useStore.getState().reviewState }),
        onSegment: (seg) => s.addSegment(seg),
        onNoteChunk: (c) => { s.noteChunk(c); s.set({ activeTab: 'note' }); },
        onRisk: (m) => { riskAcc.push({ type: m.risk_type, severity: m.severity, message: m.message, evidence_text: m.evidence_text, evidence_span_ids: [] }); s.set({ risk: { session_id: useStore.getState().sessionId || '', score: 0, markers: [...riskAcc], disclaimer: '' } }); },
        // Fast pass: structured outputs land before the note finishes streaming.
        onAnalysis: (a) => s.set({ extraction: a.extraction, risk: a.risk, grounding: a.grounding }),
        onDraft: async (d) => {
          s.set({ reviewState: d.state as API.ReviewState, grounding: d.grounding, recording: false, busy: false, activeTab: 'note' });
          await s.loadOutputs(d.session_id);   // server-provided id — avoids the stale-snapshot bug
          s.loadHistory();                     // surface the new consult in "My consultations"
          toast(`Draft ready — risk ${Math.round((d.risk_score || 0) * 100)}%.`);
        },
        // Refine pass: diarized transcript + sharpened outputs — re-fetch everything.
        onRefined: async (r) => { await s.loadOutputs(r.session_id); toast('Refined with speaker labels.'); },
        // Intelligence events (Goals 4 & 5).
        onConfidenceUpdate: (c) => s.set({
          confidenceBand: c.confidence_band as any,
          confidenceReasons: c.confidence_reasons,
        }),
        onModeSwitch: (m) => s.set({ modeNotice: m }),
        onError: (msg) => { toast(msg, true); s.set({ recording: false, busy: false }); },
      }, undefined, s.modeChoice);
      s.set({ sessionId: sid, recording: true, activeTab: 'transcript' });
      micRef.current = await startMic((pcm) => sock.sendAudio(pcm));
    } catch (e: any) {
      toast(e.message || 'could not start consult', true);
      sock.close(); s.set({ recording: false });
    }
  }

  async function stopRecord() {
    s.set({ recording: false, paused: false, busy: true });
    try { await micRef.current?.stop(); } catch { /* ignore */ }
    micRef.current = null;
    sockRef.current?.stop();
  }

  function togglePause() {
    const mic = micRef.current;
    if (!mic || !s.recording) return;
    if (mic.isPaused()) { mic.resume(); s.set({ paused: false }); toast('Recording resumed.'); }
    else { mic.pause(); s.set({ paused: true }); toast('Recording paused.'); }
  }

  async function cancelRecord() {
    // Abort the consult entirely — discard audio, tell the backend to drop the session,
    // and reset the UI. No draft is generated.
    try { await micRef.current?.stop(); } catch { /* ignore */ }
    micRef.current = null;
    try { sockRef.current?.cancel(); } catch { /* ignore */ }
    sockRef.current = null;
    s.resetSession();
    s.set({ recording: false, paused: false, busy: false });
    toast('Consultation cancelled.');
  }

  // ── REST fallbacks ─────────────────────────────────────────────────────────
  async function newSession(): Promise<string> {
    const r = await API.createSession(s.templateId, s.modeChoice);
    s.resetSession(); s.set({ sessionId: r.session_id, reviewState: r.state });
    return r.session_id;
  }
  async function simulate() {
    s.set({ busy: true });
    try { const sid = await newSession(); const r: any = await API.simulate(sid); s.set({ reviewState: r.state, grounding: r.grounding }); await s.loadOutputs(sid); s.set({ activeTab: 'note' }); toast('Draft ready (simulated).'); }
    catch (e: any) { toast(e.message, true); } finally { s.set({ busy: false }); }
  }
  async function uploadFile(file: File) {
    s.set({ busy: true });
    try { const sid = await newSession(); const r: any = await API.uploadAudio(sid, file, file.name); s.set({ reviewState: r.state, grounding: r.grounding }); await s.loadOutputs(sid); s.set({ activeTab: 'note' }); toast('Draft ready.'); }
    catch (e: any) { toast('STT/processing failed: ' + e.message, true); } finally { s.set({ busy: false }); }
  }

  async function doTransition(state: string, extra: any = {}) {
    if (!s.sessionId) return;
    try { const r: any = await API.transition(s.sessionId, { state, ...extra }); s.set({ reviewState: r.state }); s.loadHistory(); toast('→ ' + state.replace('_', ' ')); return r; }
    catch (e: any) { toast(e.message, true); throw e; }
  }

  const live = s.recording || s.busy;
  const downloadExport = (fmt: string) => {
    if (!s.sessionId) return;
    fetch(API.exportUrl(s.sessionId, fmt), { headers: API.authHeaders() }).then(async (r) => {
      if (!r.ok) { toast('export failed (finalize first)', true); return; }
      const blob = await r.blob(); const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `${s.sessionId}.${fmt === 'markdown' ? 'md' : fmt}`; a.click(); URL.revokeObjectURL(url);
    });
  };

  const recorderProps = {
    recording: s.recording, paused: s.paused, busy: live, streaming: s.streaming, stage: s.stage,
    templates: s.templates, templateId: s.templateId, onTemplate: (t: string) => s.set({ templateId: t }),
    onRecord: record, onSimulate: simulate, onPause: togglePause, onCancel: cancelRecord,
    onUpload: (f: File) => uploadFile(f), analyser: micRef.current?.analyser || null,
    modeChoice: s.modeChoice, onModeChoice: (v: any) => { s.set({ modeChoice: v }); localStorage.setItem('svaani-mode', v); }
  };

  if (!s.sessionId && !live) {
    const greetingName = session?.user?.user_metadata?.full_name || session?.user?.email?.split('@')[0] || 'Doctor';
    const hour = new Date().getHours();
    const greeting = hour < 12 ? 'Good morning Dr' : hour < 17 ? 'Good afternoon Dr' : hour < 21 ? 'Good evening Dr' : 'Good night Dr';

    return (
      <>
        <NoticeBanner notice={s.modeNotice} onDismiss={() => s.set({ modeNotice: null })} />
        <div className="relative flex flex-col items-center justify-center h-full w-full overflow-hidden">
          
          {/* Decorative soft blue gradient glow at the bottom (seamless) */}
          <div className="absolute bottom-[-10%] left-1/2 -translate-x-1/2 w-[1200px] h-[600px] rounded-[100%] bg-gradient-to-t from-sky-300/40 via-sky-200/20 to-transparent blur-[120px] pointer-events-none z-0"></div>
          
          <div className="flex flex-col items-center justify-center w-full max-w-4xl mx-auto px-6 animate-in fade-in zoom-in-95 duration-500 z-10 pb-12">
            <h1 className="text-[2.5rem] text-slate-800 font-semibold mb-12 tracking-tight">
              {greeting}, <span className="text-slate-500">{greetingName}</span>
            </h1>
            <Recorder variant="center" {...recorderProps} />
          </div>
        </div>
      </>
    );
  }

  return (
    <div className="flex flex-col h-full w-full bg-[#eef1f7]">
      <NoticeBanner notice={s.modeNotice} onDismiss={() => s.set({ modeNotice: null })} />

      <main className="flex flex-1 overflow-hidden animate-in fade-in duration-500 relative">
        <section className="flex-1 flex flex-col overflow-y-auto hidden-scrollbar relative p-4 md:p-6 pt-0">
          <Tabs 
            active={s.activeTab} 
            onTab={(t) => s.set({ activeTab: t })} 
            role={s.role} 
            rightAction={
              s.sessionId && !s.reviewSubmitted && s.reviewState && !['listening', 'processing'].includes(s.reviewState) ? (
                <button
                  onClick={() => s.set({ isReviewModalOpen: true })}
                  className="bg-sky-600 hover:bg-sky-700 text-white font-medium py-1.5 px-4 rounded-full text-sm shadow-sm transition-all flex items-center gap-2 active:scale-95"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
                  Review & Sign-off
                </button>
              ) : null
            }
          />
          <div className="tabbody max-w-4xl mx-auto w-full pb-32">
            {s.activeTab === 'note' && <NoteView />}
            {s.activeTab === 'risk' && <RiskPanel />}
            {s.activeTab === 'extraction' && <ExtractionEditor />}
            {s.activeTab === 'transcript' && <TranscriptView />}
            {s.activeTab === 'grounding' && <GroundingPanel />}
            {s.activeTab === 'speakers' && <SpeakerTimeline />}
            {s.activeTab === 'prescription' && <PrescriptionPreview />}
            {s.activeTab === 'admin' && <AdminDashboard />}
          </div>
        </section>

        {live && (
          <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-8 fade-in duration-300">
            <Recorder variant="floating" {...recorderProps} />
          </div>
        )}
      </main>

      <ReviewModal 
        isOpen={s.isReviewModalOpen} 
        onClose={() => s.set({ isReviewModalOpen: false })}
        sessionId={s.sessionId!}
        reviewState={s.reviewState}
        onTransition={doTransition}
        onExport={downloadExport}
      />
    </div>
  );
}
