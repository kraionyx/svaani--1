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
import { SignOff } from '../components/SignOff';
import { NoticeBanner } from '../components/NoticeBanner';
import { SpeakerTimeline } from '../components/SpeakerTimeline';
import { ReviewPrompt } from '../components/ReviewPrompt';
import { PrescriptionPreview } from '../components/PrescriptionPreview';
import { AdminDashboard } from '../components/AdminDashboard';
import { ThreeScene } from '../components/ThreeScene';

function formatSessionDate(isoString?: string | null) {
  if (!isoString) return '';
  const d = new Date(isoString);
  if (isNaN(d.getTime())) return '';
  const datePart = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const timePart = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  return `${datePart}, ${timePart}`;
}

export function ScribeWorkspace() {
  const s = useStore();
  const { session } = useAuth();
  const sockRef = useRef<ConsultSocket | null>(null);
  const micRef = useRef<MicHandle | null>(null);
  const [signOpen, setSignOpen] = useState(false);
  const [history, setHistory] = useState<API.SessionSummary[]>([]);
  const [filterQuery, setFilterQuery] = useState('');

  const loadHistory = () => { API.listSessions().then(setHistory).catch(() => { }); };

  useEffect(() => {
    loadHistory();
  }, []);

  // Reopen one of the user's past consultations (loads its saved outputs).
  async function openSession(sid: string) {
    try {
      s.resetSession();
      const meta: any = await API.api(`/sessions/${sid}`);
      s.set({ sessionId: sid, reviewState: meta.state, activeTab: 'note' });
      await loadOutputs(sid);
    } catch (e: any) { toast(e.message || 'could not open consultation', true); }
  }

  async function loadOutputs(sid: string) {
    const [note, risk, extraction, raw, clean] = await Promise.all(
      ['note', 'risk', 'extraction', 'raw', 'clean'].map((k) => API.getOutput(sid, k).catch(() => null)),
    );
    // Don't force the active tab here — the refine pass calls this while the user may be
    // viewing another tab; callers that should land on the note set it explicitly.
    s.set({ note, risk, extraction, raw, clean });

    if (raw && raw.segments && Array.isArray(raw.segments)) {
      const mapped = raw.segments.map((x: any) => ({
        speaker: x.speaker || 'unknown',
        text: x.text || '',
        span_id: x.id || x.span_id || `legacy-${Math.random()}`,
        final: true,
      }));
      s.replaceSegments(mapped);
    }
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
          loadHistory();                     // surface the new consult in "My consultations"
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
    try { const r: any = await API.transition(s.sessionId, { state, ...extra }); s.set({ reviewState: r.state }); loadHistory(); toast('→ ' + state.replace('_', ' ')); return r; }
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

  return (
    <>
      <NoticeBanner notice={s.modeNotice} onDismiss={() => s.set({ modeNotice: null })} />

      <main className="grid">
        <aside className="left">
          <Recorder
            recording={s.recording} paused={s.paused} busy={live} streaming={s.streaming} stage={s.stage}
            templates={s.templates} templateId={s.templateId} onTemplate={(t) => s.set({ templateId: t })}
            onRecord={record} onSimulate={simulate}
            onPause={togglePause} onCancel={cancelRecord}
            onUpload={(f) => uploadFile(f)}
            analyser={micRef.current?.analyser || null}
            modeChoice={s.modeChoice}
            onModeChoice={(v) => { s.set({ modeChoice: v }); localStorage.setItem('svaani-mode', v); }}
          />
          {s.sessionId && (
            <SignOff
              state={s.reviewState} hasNote={!!s.note} signOpen={signOpen}
              onTransition={doTransition} onOpenSign={() => setSignOpen(true)} onCloseSign={() => setSignOpen(false)}
              onExport={downloadExport}
            />
          )}
          {s.sessionId && !s.reviewSubmitted && s.reviewState && !['listening', 'processing'].includes(s.reviewState) && (
            <ReviewPrompt sessionId={s.sessionId} onSubmit={() => s.set({ reviewSubmitted: true })} />
          )}
          {session && history.length > 0 && (
            <div className="card" style={{ marginTop: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <b>My consultations</b>
                <button onClick={loadHistory} title="Refresh" className="btn ghost sm" style={{ padding: '2px 8px' }}>↻</button>
              </div>
              <input
                type="text"
                className="consultations-search"
                placeholder="Search ID, template, state..."
                value={filterQuery}
                onChange={(e) => setFilterQuery(e.target.value)}
              />
              <ul className="consultations-list">
                {history.filter((h) => {
                  const q = filterQuery.toLowerCase();
                  return h.session_id.toLowerCase().includes(q) || (h.template_id || '').toLowerCase().includes(q) || (h.state || '').toLowerCase().includes(q) || (h.signed_by_name || '').toLowerCase().includes(q);
                }).map((h) => (
                  <li key={h.session_id} className={`consultation-item ${h.session_id === s.sessionId ? 'active' : ''}`} onClick={() => openSession(h.session_id)}>
                    <div className="consultation-header">
                      <span className="consultation-id">{h.session_id.replace('sess-', '')}</span>
                      {h.template_id && <span className="consultation-tag">{h.template_id}</span>}
                    </div>
                    <div className="consultation-footer">
                      <span className="consultation-date">{formatSessionDate(h.created_at)}</span>
                      <span className={`state-badge ${h.state}`}>{h.state.replace(/_/g, ' ')}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>

        <section className="right">
          {!s.sessionId && !live ? (
            <div className="empty-scene-container">
              <ThreeScene recording={s.recording} busy={s.busy} />
              <div className="empty-scene-overlay">
                <div className="empty-card-glass">
                  <h2>Svaani. Scribe</h2>
                  <p>Start a consult — record live (streaming), upload audio, or simulate from the capture panel.</p>
                  <div className="pulse-indicator">
                    <span className="pulse-dot"></span>
                    System Active &amp; Ready
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <>
              <Tabs active={s.activeTab} onTab={(t) => s.set({ activeTab: t })} role={s.role} />
              <div className="tabbody">
                {s.activeTab === 'note' && <NoteView />}
                {s.activeTab === 'risk' && <RiskPanel />}
                {s.activeTab === 'extraction' && <ExtractionEditor />}
                {s.activeTab === 'transcript' && <TranscriptView />}
                {s.activeTab === 'grounding' && <GroundingPanel />}
                {s.activeTab === 'speakers' && <SpeakerTimeline />}
                {s.activeTab === 'prescription' && <PrescriptionPreview />}
                {s.activeTab === 'admin' && <AdminDashboard />}
              </div>
            </>
          )}
        </section>
      </main>
    </>
  );
}
