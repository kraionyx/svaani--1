import { useEffect, useRef, useState } from 'react';
import * as API from './api';
import { useStore } from './store';
import { onToast, toast } from './toast';
import { ConsultSocket } from './ws';
import { startMic, micSupported, type MicHandle } from './audio';
import { Recorder } from './components/Recorder';
import { Tabs } from './components/Tabs';
import { NoteView } from './components/NoteView';
import { RiskPanel } from './components/RiskPanel';
import { ExtractionEditor } from './components/ExtractionEditor';
import { GroundingPanel } from './components/GroundingPanel';
import { TranscriptView } from './components/TranscriptView';
import { SignOff } from './components/SignOff';
import { NotificationsSidebar, type Notification } from './components/NotificationsSidebar';
import { ConfidenceChip } from './components/ConfidenceChip';
import { NoticeBanner } from './components/NoticeBanner';
import { SpeakerTimeline } from './components/SpeakerTimeline';
import { ReviewPrompt } from './components/ReviewPrompt';
import { AiEditor } from './components/AiEditor';
import { PrescriptionPreview } from './components/PrescriptionPreview';
import { AdminDashboard } from './components/AdminDashboard';

const THEMES = ['mint', 'white', 'dark'];

export function App() {
  const s = useStore();
  const [toastMsg, setToastMsg] = useState<{ m: string; e: boolean } | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [showNotifs, setShowNotifs] = useState(false);
  const notifIdRef = useRef(0);
  const sockRef = useRef<ConsultSocket | null>(null);
  const micRef = useRef<MicHandle | null>(null);
  const [signOpen, setSignOpen] = useState(false);

  useEffect(() => {
    onToast((m, e) => { 
      setToastMsg({ m, e }); 
      setTimeout(() => setToastMsg(null), e ? 6500 : 3000); 
      setNotifications(prev => [{ id: ++notifIdRef.current, m, e, time: new Date() }, ...prev]);
    });
    API.getHealth().then((h) => s.set({ health: h })).catch(() => toast('backend unreachable on :8000', true));
    API.listTemplates().then((t) => {
      s.set({ templates: t });
      if (t.find((x) => x.template_id === 'ent')) s.set({ templateId: 'ent' });
      else if (t[0]) s.set({ templateId: t[0].template_id });
    }).catch(() => {});
  }, []);

  const setTheme = (t: string) => { document.documentElement.dataset.theme = t; localStorage.setItem('svaani-theme', t); s.set({} as any); };

  async function loadOutputs(sid: string) {
    const [note, risk, extraction, raw, clean] = await Promise.all(
      ['note', 'risk', 'extraction', 'raw', 'clean'].map((k) => API.getOutput(sid, k).catch(() => null)),
    );
    // Don't force the active tab here — the refine pass calls this while the user may be
    // viewing another tab; callers that should land on the note set it explicitly.
    s.set({ note, risk, extraction, raw, clean });
  }

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
          await loadOutputs(d.session_id);   // server-provided id — avoids the stale-snapshot bug
          toast(`Draft ready — risk ${Math.round((d.risk_score || 0) * 100)}%.`);
        },
        // Refine pass: diarized transcript + sharpened outputs — re-fetch everything.
        onRefined: async (r) => { await loadOutputs(r.session_id); toast('Refined with speaker labels.'); },
        // Intelligence events (Goals 4 & 5).
        onConfidenceUpdate: (c) => s.set({
          confidenceBand: c.confidence_band as any,
          confidenceReasons: c.confidence_reasons,
        }),
        onModeSwitch: (m) => s.set({ modeNotice: m }),
        onError: (msg) => { toast(msg, true); s.set({ recording: false, busy: false }); },
      });
      s.set({ sessionId: sid, recording: true, activeTab: 'transcript' });
      micRef.current = await startMic((pcm) => sock.sendAudio(pcm));
    } catch (e: any) {
      toast(e.message || 'could not start consult', true);
      sock.close(); s.set({ recording: false });
    }
  }

  async function stopRecord() {
    s.set({ recording: false, busy: true });
    try { await micRef.current?.stop(); } catch { /* ignore */ }
    micRef.current = null;
    sockRef.current?.stop();
  }

  // ── REST fallbacks ─────────────────────────────────────────────────────────
  async function newSession(): Promise<string> {
    const r = await API.createSession(s.templateId);
    s.resetSession(); s.set({ sessionId: r.session_id, reviewState: r.state });
    return r.session_id;
  }
  async function simulate() {
    s.set({ busy: true });
    try { const sid = await newSession(); const r: any = await API.simulate(sid); s.set({ reviewState: r.state, grounding: r.grounding }); await loadOutputs(sid); s.set({ activeTab: 'note' }); toast('Draft ready (simulated).'); }
    catch (e: any) { toast(e.message, true); } finally { s.set({ busy: false }); }
  }
  async function uploadFile(file: File) {
    s.set({ busy: true });
    try { const sid = await newSession(); const r: any = await API.uploadAudio(sid, file, file.name); s.set({ reviewState: r.state, grounding: r.grounding }); await loadOutputs(sid); s.set({ activeTab: 'note' }); toast('Draft ready.'); }
    catch (e: any) { toast('STT/processing failed: ' + e.message, true); } finally { s.set({ busy: false }); }
  }

  async function doTransition(state: string, extra: any = {}) {
    if (!s.sessionId) return;
    try { const r: any = await API.transition(s.sessionId, { state, ...extra }); s.set({ reviewState: r.state }); toast('→ ' + state.replace('_', ' ')); return r; }
    catch (e: any) { toast(e.message, true); throw e; }
  }

  const live = s.recording || s.busy;
  const isReviewing = !!s.sessionId && !live;
  const downloadExport = (fmt: string) => {
    if (!s.sessionId) return;
    fetch(API.exportUrl(s.sessionId, fmt), { headers: API.authHeaders() }).then(async (r) => {
      if (!r.ok) { toast('export failed (finalize first)', true); return; }
      const blob = await r.blob(); const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = `${s.sessionId}.${fmt === 'markdown' ? 'md' : fmt}`; a.click(); URL.revokeObjectURL(url);
    });
  };

  return (
    <div className="shell" style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', width: '100%' }}>
      <header className="topbar">
        <div className="brand">
          <span className="logo">𝓢</span>
          <div className="brand-id">
            <b>Svaani<span className="dot">.</span></b>
            <span className="sub">AI Medical Scribe</span>
          </div>
          <svg className="ekg" viewBox="0 0 132 24" aria-hidden="true" focusable="false">
            <path d="M0 12 H46 l3.5 -8 l4.5 16 l4 -13 l3 5 H78 l3.5 -10 l4.5 18 l3 -8 H132" />
          </svg>
        </div>
        <div className="topctrls">
          <span className={`pill ${s.health?.sarvam === 'live' ? 'live' : 'mock'}`}><span className="d" />STT: {s.health?.sarvam || '…'}</span>
          <span className={`pill ${s.health?.vertex === 'live' ? 'live' : 'mock'}`}><span className="d" />LLM: {s.health?.vertex || '…'}</span>
          {s.confidenceBand && (
            <ConfidenceChip band={s.confidenceBand} reasons={s.confidenceReasons} />
          )}
          <label className="ctrl">role
            <select value={s.role} onChange={(e) => { s.set({ role: e.target.value }); API.setRole(e.target.value); }}>
              <option value="doctor">doctor</option><option value="scribe">scribe</option><option value="admin">admin</option>
            </select>
          </label>
          <div className="seg-theme">{THEMES.map((t) => <button key={t} className={document.documentElement.dataset.theme === t ? 'active' : ''} onClick={() => setTheme(t)}>{t[0].toUpperCase() + t.slice(1)}</button>)}</div>
          
          <div style={{ position: 'relative' }}>
            <button className="btn ghost sm" onClick={() => setShowNotifs(true)} style={{ padding: '4px 8px', background: 'transparent', display: 'flex', alignItems: 'center' }}>
              <svg viewBox="0 0 24 24" width="20" height="20" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
              </svg>
              {notifications.length > 0 && <span style={{ position: 'absolute', top: '-2px', right: '-2px', background: 'var(--critical)', color: 'white', borderRadius: '50%', width: '16px', height: '16px', fontSize: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{notifications.length}</span>}
            </button>
          </div>
        </div>
      </header>

      <NoticeBanner notice={s.modeNotice} onDismiss={() => s.set({ modeNotice: null })} />

      <div style={{ display: 'flex', flexDirection: 'row', flex: 1, width: '100%' }}>
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          {isReviewing && s.sessionId && (
            <SignOff
              state={s.reviewState} hasNote={!!s.note} signOpen={signOpen}
              onTransition={doTransition} onOpenSign={() => setSignOpen(true)} onCloseSign={() => setSignOpen(false)}
              onExport={downloadExport}
            />
          )}

          <main className="center-layout">
            {!isReviewing ? (
              <div className="center-container">
                <Recorder
                  recording={s.recording} busy={live} streaming={s.streaming} stage={s.stage}
                  templates={s.templates} templateId={s.templateId} onTemplate={(t) => s.set({ templateId: t })}
                  onRecord={record} onSimulate={simulate}
                  onUpload={(f) => uploadFile(f)}
                  analyser={micRef.current?.analyser || null}
                />
              </div>
            ) : (
              <div className="center-container" style={{ maxWidth: '1200px', width: '100%', marginTop: 'var(--space-md)' }}>
                {s.sessionId && !s.reviewSubmitted && s.reviewState && !['listening', 'processing'].includes(s.reviewState) && (
                  <ReviewPrompt sessionId={s.sessionId} onSubmit={() => s.set({ reviewSubmitted: true })} />
                )}
                <section className="right" style={{ padding: 0 }}>
                  <Tabs active={s.activeTab} onTab={(t) => s.set({ activeTab: t })} role={s.role} />
                  <div className="tabbody">
                    {s.activeTab === 'note' && <NoteView />}
                    {s.activeTab === 'risk' && <RiskPanel />}
                    {s.activeTab === 'extraction' && <ExtractionEditor />}
                    {s.activeTab === 'transcript' && <TranscriptView />}
                    {s.activeTab === 'grounding' && <GroundingPanel />}
                    {s.activeTab === 'speakers' && <SpeakerTimeline />}
                    {s.activeTab === 'ai-edit' && <AiEditor />}
                    {s.activeTab === 'prescription' && <PrescriptionPreview />}
                    {s.activeTab === 'admin' && <AdminDashboard />}
                  </div>
                </section>
              </div>
            )}
          </main>

          <footer className="app-footer">
            <p className="hint">Record uses real-time streaming STT; on stop, the consult is diarized and the note streams in.</p>
          </footer>
        </div>

        <NotificationsSidebar 
          open={showNotifs} 
          notifications={notifications} 
          onClose={() => setShowNotifs(false)} 
          onClear={() => setNotifications([])} 
        />
      </div>

      {toastMsg && <div className={`toast ${toastMsg.e ? 'err' : ''}`}>{toastMsg.m}</div>}
    </div>
  );
}
