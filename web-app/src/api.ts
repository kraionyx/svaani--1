// REST client + shared types for the Svaani backend (FastAPI on :8000).

export const API_BASE = (() => {
  const p = location.port;
  if (location.protocol === 'file:') return 'http://127.0.0.1:8000';
  if (p === '' || p === '8000') return '';
  return `${location.protocol}//${location.hostname}:8000`;
})();

export const WS_BASE = (() => {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = API_BASE ? API_BASE.replace(/^https?:/, proto) : `${proto}//${location.host}`;
  return host;
})();

export let ROLE = localStorage.getItem('svaani-role') || 'doctor';
export const setRole = (r: string) => { ROLE = r; localStorage.setItem('svaani-role', r); };

function headers(extra: Record<string, string> = {}) {
  return { 'X-User-Id': 'dashboard', 'X-Role': ROLE, ...extra };
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(API_BASE + path, { ...opts, headers: headers((opts.headers as any) || {}) });
  if (!r.ok) {
    let d: any; try { d = await r.json(); } catch { d = { detail: r.statusText }; }
    throw new Error(d.detail || `HTTP ${r.status}`);
  }
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : (r as any);
}

export const jsonBody = (b: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b),
});

// ── Types (mirror the backend pydantic schemas) ──────────────────────────────
export interface Provenance { span_ids: string[]; confidence: number; grounded: boolean; note?: string | null; }
export interface ChiefComplaint { symptom: string; duration?: string | null; type?: string | null; provenance: Provenance; }
export interface Allergy { substance: string; reaction?: string | null; provenance: Provenance; }
export interface Medication { name: string; dose?: string | null; route?: string | null; frequency?: string | null; duration?: string | null; verbatim_text?: string; authoritative: boolean; provenance: Provenance; }
export interface ExaminationFinding { region: string; finding: string; value: any; provenance: Provenance; }
export interface GroundedText { text: string; provenance: Provenance; }
export interface Extraction {
  session_id: string;
  chief_complaints: ChiefComplaint[];
  history_of_present_illness?: GroundedText | null;
  past_medical_history: GroundedText[];
  family_history: GroundedText[];
  allergies: Allergy[];
  vitals: Record<string, string>;
  examination: ExaminationFinding[];
  investigations: GroundedText[];
  assessment?: GroundedText | null;
  diagnosis: GroundedText[];
  treatment_plan: GroundedText[];
  medications_discussed: Medication[];
  follow_up?: GroundedText | null;
  doctor_notes?: GroundedText | null;
  [k: string]: any;
}
export interface NoteSection { section_id: string; label: string; component: string; order: number; content_text: string; content_data: any; empty: boolean; }
export interface Note { session_id: string; template_id: string; template_version: number; sections: NoteSection[]; }
export interface RiskMarker { type: string; severity: string; message: string; evidence_span_ids: string[]; evidence_text?: string; }
export interface Risk { session_id: string; score: number; markers: RiskMarker[]; disclaimer: string; }
export interface Grounding { kept: number; dropped: string[]; flagged: string[]; verified: string[]; mismatched: string[]; }
export interface Segment { id: string; speaker: string; text: string; language: string; confidence: number; }
export interface RawTranscript { session_id: string; segments: Segment[]; }
export interface CleanTranscript { session_id: string; segments: Segment[]; corrections: any[]; low_confidence_span_ids: string[]; }
export type ReviewState = 'listening' | 'processing' | 'draft' | 'in_review' | 'edited' | 'approved' | 'finalized' | 'escalation_required';

// ── REST calls ───────────────────────────────────────────────────────────────
export const getHealth = () => api<{ sarvam: string; vertex: string }>('/health');
export const listTemplates = () => api<{ template_id: string; name: string }[]>('/templates');
export const createSession = (template_id: string) =>
  api<{ session_id: string; state: ReviewState }>('/sessions', jsonBody({ template_id }));
export const simulate = (sid: string) => api(`/sessions/${sid}/simulate`, { method: 'POST' });
export const getOutput = <T = any>(sid: string, kind: string) => api<T>(`/sessions/${sid}/outputs/${kind}`);
export const transition = (sid: string, body: any) => api(`/sessions/${sid}/state`, jsonBody(body));
export const saveNote = (sid: string, sections: { section_id: string; content_text: string }[]) =>
  api(`/sessions/${sid}/note`, jsonBody({ sections }));
export const saveExtraction = (sid: string, extraction: Extraction) =>
  api(`/sessions/${sid}/extraction`, { ...jsonBody({ extraction }), method: 'PUT' });
export const saveRisk = (sid: string, markers: RiskMarker[]) =>
  api(`/sessions/${sid}/risk`, { ...jsonBody({ markers }), method: 'PUT' });

export async function uploadAudio(sid: string, file: Blob, name = 'consult.wav') {
  const fd = new FormData(); fd.append('file', file, name);
  return api(`/sessions/${sid}/audio`, { method: 'POST', body: fd });
}
export function exportUrl(sid: string, fmt: string) { return `${API_BASE}/sessions/${sid}/export/${fmt}`; }
export { headers as authHeaders };
