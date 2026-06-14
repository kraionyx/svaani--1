// Streaming consultation client over the backend WebSocket (/ws/consultation).
import { WS_BASE, type Extraction, type Grounding, type Risk } from './api';

export interface ConsultEvents {
  onStage?: (stage: string, streaming?: boolean) => void;
  onSegment?: (s: { speaker: string; text: string; span_id: string; final?: boolean }) => void;
  onNoteChunk?: (c: { section_id: string; label?: string; delta?: string; start?: boolean; done?: boolean }) => void;
  onRisk?: (m: { severity: string; risk_type: string; message: string; evidence_text?: string }) => void;
  // Fast pass: structured outputs ready (populates tabs before the note finishes streaming).
  onAnalysis?: (a: { session_id: string; extraction: Extraction; risk: Risk; grounding: Grounding }) => void;
  onDraft?: (d: { session_id: string; state: string; risk_score: number; note_markdown: string; grounding: Grounding }) => void;
  // Refine pass: diarized transcript + sharpened outputs are ready to re-fetch.
  onRefined?: (r: { session_id: string; risk_score: number; grounding: Grounding }) => void;
  onError?: (msg: string) => void;
  onClose?: () => void;
}

export class ConsultSocket {
  private ws: WebSocket | null = null;

  connect(templateId: string, ev: ConsultEvents, sessionId?: string): Promise<string> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`${WS_BASE}/ws/consultation`);
      ws.binaryType = 'arraybuffer';
      this.ws = ws;
      let sid = sessionId || '';
      ws.onopen = () => ws.send(JSON.stringify({ action: 'start', template_id: templateId, session_id: sessionId }));
      ws.onerror = () => reject(new Error('WebSocket connection failed — is the backend running on :8000?'));
      ws.onclose = () => ev.onClose?.();
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data);
        switch (m.type) {
          case 'stage_update':
            if (m.session_id) { sid = m.session_id; resolve(sid); }
            ev.onStage?.(m.stage, m.streaming); break;
          case 'final_segment': ev.onSegment?.(m); break;
          case 'note_chunk': ev.onNoteChunk?.(m); break;
          case 'risk_warning': ev.onRisk?.(m); break;
          case 'analysis': ev.onAnalysis?.(m); break;
          case 'draft_ready': ev.onDraft?.(m); break;
          case 'refined': ev.onRefined?.(m); break;
          case 'error': ev.onError?.(m.message); break;
        }
      };
    });
  }

  sendAudio(pcm: Int16Array) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm.buffer as ArrayBuffer);
  }
  stop() { if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ action: 'stop' })); }
  close() { try { this.ws?.close(); } catch { /* ignore */ } this.ws = null; }
}
