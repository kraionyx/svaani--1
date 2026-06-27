// REST client + shared types for the Svaani backend (FastAPI on :8000).

export const API_BASE = (() => {
  const p = location.port;
  if (location.protocol === 'file:') return 'http://127.0.0.1:8000';
  if (p === '' || p === '8000') return '';
  const host = location.hostname === 'localhost' ? '127.0.0.1' : location.hostname;
  return `${location.protocol}//${host}:8000`;
})();

export const WS_BASE = (() => {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = API_BASE ? API_BASE.replace(/^https?:/, proto) : `${proto}//${location.host}`;
  return host;
})();

export let ROLE = localStorage.getItem('svaani-role') || 'doctor';
export const setRole = (r: string) => { ROLE = r; localStorage.setItem('svaani-role', r); };

// Supabase access token, kept in sync by the AuthProvider (auth.tsx). When present we send
// it as a verified Bearer token; when absent we fall back to the dev header scaffold so the
// app still works in SCRIBE_AUTH_MODE=dev with no login.
let ACCESS_TOKEN: string | null = null;
export const setAuthToken = (t: string | null) => { ACCESS_TOKEN = t; };
export const getAuthToken = () => ACCESS_TOKEN;

function headers(extra: Record<string, string> = {}) {
  if (ACCESS_TOKEN) return { Authorization: `Bearer ${ACCESS_TOKEN}`, ...extra };
  return { 'X-User-Id': 'dashboard', 'X-Role': ROLE, ...extra };
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(API_BASE + path, { ...opts, headers: headers((opts.headers as any) || {}) });
  if (!r.ok) {
    let d: any; try { d = await r.json(); } catch { d = { detail: r.statusText }; }
    const det = d.detail;
    const msg = typeof det === 'string' ? det
      : Array.isArray(det) ? det.map((e: any) => e.msg || JSON.stringify(e)).join('; ')
      : `HTTP ${r.status}`;
    throw new Error(msg);
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

// ── My consultations (per-user) ───────────────────────────────────────────────
export interface SessionSummary {
  session_id: string; state: ReviewState; template_id: string | null;
  signed_by_name?: string | null; has_note?: boolean | null;
  created_at?: string | null; updated_at?: string | null;
}
export const listSessions = () => api<SessionSummary[]>('/sessions');
export const createSession = (template_id: string, mode: 'realtime' | 'batch' | 'auto' | 'hybrid' = 'realtime') =>
  api<{ session_id: string; state: ReviewState }>('/sessions', jsonBody({ template_id, mode }));
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

// ── Intelligence / profile types ─────────────────────────────────────────────
export interface SpeakerProfile {
  speaker_label: string;
  role: string;
  relationship: string;
  subject_patient?: string | null;
  span_ids?: string[];
  confidence: number;
}
export interface ReferencedSubject { label: string; relationship: string; evidence_span_ids: string[]; }
export interface ConversationProfile {
  session_id: string;
  inference_mode?: string | null;
  kind: string;
  speakers: SpeakerProfile[];
  speaker_count: number;
  referenced_patient?: string | null;
  referenced_subjects?: ReferencedSubject[];
  complexity_score: number;
  is_complex: boolean;
  confidence_band: 'high' | 'moderate' | 'low';
  confidence_pct: number;
  confidence_reasons: string[];
  complexity_signals: string[];
}

// ── Review / admin / ops types ─────────────────────────────────────────────
export interface ReviewPayload {
  rating: 'helpful' | 'needs_improvement';
  error_categories?: string[];
  comment?: string | null;
}
export interface AdminReviewEntry {
  review: any;
  admin_review: { id: string; status: string; admin_notes?: string | null; created_at: string; assigned_to?: string | null };
}
export interface ImprovementItem {
  id: string; stage: string; review_id: string; created_at: string;
  candidate_prompt?: string | null; eval_results?: any; approved_by?: string | null;
}
export interface PromptVersion {
  id: string; name: string; version: number; content: string; content_hash: string;
  active: boolean; created_at: string; created_by?: string | null;
}

// ── Document types ────────────────────────────────────────────────────────
export interface RenderedDocument {
  id: string; session_id: string; doc_type: string; status: string;
  rendered_html: string; edited_html?: string | null;
  approved_at?: string | null; approved_by?: string | null;
}

// ── AI editor types ───────────────────────────────────────────────────────
export interface AiEditChange { section_id: string; before?: string; after?: string; content_text?: string; }
export interface EditEntry {
  seq: number; section_id: string; before: string; after: string;
  instruction: string; applied: boolean; undone?: boolean;
}

// ── New API calls ─────────────────────────────────────────────────────────
export const getProfile = (sid: string) => api<ConversationProfile>(`/sessions/${sid}/profile`);

export const patchSpeakers = (sid: string, body: {
  corrections: { speaker_label: string; role?: string; relationship?: string; subject_patient?: string }[];
  referenced_patient?: string;
}) => api<{ session_id: string; referenced_patient: string | null; speakers: SpeakerProfile[]; note: Note | null }>(
  `/sessions/${sid}/speakers`, { ...jsonBody(body), method: 'PATCH' }
);

export const submitReview = (sid: string, body: ReviewPayload) =>
  api<{ review_id: string; rating: string }>(`/sessions/${sid}/review`, jsonBody(body));

export const getAdminReviews = (status?: string) =>
  api<AdminReviewEntry[]>(`/admin/reviews${status ? `?status=${status}` : ''}`);

export const patchAdminReview = (id: string, body: { status: string; admin_notes?: string }) =>
  api(`/admin/reviews/${id}`, { ...jsonBody(body), method: 'PATCH' });

export const getImprovements = (stage?: string) =>
  api<ImprovementItem[]>(`/admin/improvements${stage ? `?stage=${stage}` : ''}`);

export const advanceImprovement = (id: string, body: { candidate_prompt?: string; reject?: boolean } = {}) =>
  api<ImprovementItem>(`/admin/improvements/${id}/advance`, jsonBody(body));

export const getPrompts = (name?: string) => api<PromptVersion[]>(`/prompts${name ? `?name=${name}` : ''}`);

export const createPrompt = (body: { name: string; content: string; activate?: boolean }) =>
  api<PromptVersion>('/prompts', jsonBody(body));

export const activatePrompt = (id: string) => api<PromptVersion>(`/prompts/${id}/activate`, { method: 'POST' });

export const aiEditPreview = (sid: string, body: { instruction: string }) =>
  api<{ instruction: string; changes: AiEditChange[] }>(`/sessions/${sid}/ai-edit`, jsonBody(body));

export const aiEditApply = (sid: string, body: { instruction: string; changes: { section_id: string; content_text: string }[] }) =>
  api<{ session_id: string; state: string; note: Note }>(`/sessions/${sid}/ai-edit/apply`, jsonBody(body));

export const getEdits = (sid: string) => api<EditEntry[]>(`/sessions/${sid}/edits`);

export const aiEditUndo = (sid: string) =>
  api<{ session_id: string; state: string; seq: number; note: Note }>(`/sessions/${sid}/ai-edit/undo`, { method: 'POST' });

export const aiEditRedo = (sid: string) =>
  api<{ session_id: string; state: string; seq: number; note: Note }>(`/sessions/${sid}/ai-edit/redo`, { method: 'POST' });

// Structured-tab AI edits (Extraction, Risk). Preview returns readable before/after
// `changes` for the UI plus the full `proposed` object the apply route needs.
export interface AiEditProposal { instruction: string; changes: AiEditChange[]; proposed?: any; }

export const aiEditExtractionPreview = (sid: string, body: { instruction: string }) =>
  api<AiEditProposal>(`/sessions/${sid}/ai-edit/extraction`, jsonBody(body));

export const aiEditExtractionApply = (sid: string, body: { instruction: string; proposed: Extraction }) =>
  api<{ session_id: string; state: string; extraction: Extraction; note: Note; grounding: Grounding }>(
    `/sessions/${sid}/ai-edit/extraction/apply`, jsonBody(body));

export const aiEditRiskPreview = (sid: string, body: { instruction: string }) =>
  api<AiEditProposal>(`/sessions/${sid}/ai-edit/risk`, jsonBody(body));

export const aiEditRiskApply = (sid: string, body: { instruction: string; proposed: RiskMarker[] }) =>
  api<{ session_id: string; state: string; risk: Risk }>(`/sessions/${sid}/ai-edit/risk/apply`, jsonBody(body));

// ── Eval harness + A/B + analytics (admin) ──────────────────────────────────
export const runImprovementEval = (id: string, body: { candidate_prompt?: string; dataset?: string; prompt_name?: string } = {}) =>
  api<{ dataset: string; n_cases: number; attribution: number; passed: boolean; failures: string[] }>(
    `/admin/improvements/${id}/eval`, jsonBody(body));

export const getImprovementEval = (id: string) => api<any>(`/admin/improvements/${id}/eval`);

export const setPromptAb = (name: string, body: { enabled: boolean; b_version_id?: string; b_pct: number }) =>
  api<{ key: string; enabled: boolean; value: any }>(`/admin/prompts/${name}/ab`, jsonBody(body));

export const getPromptAbMetrics = (name: string) =>
  api<{ prompt_name: string; arms: Record<string, { n: number; helpful: number; needs_improvement: number; needs_improvement_rate: number }>; total: number }>(
    `/admin/prompts/${name}/ab/metrics`);

export const getErrorAnalytics = () =>
  api<{ total_reviews: number; by_error_category: Record<string, number>; by_rating: Record<string, number>; by_inference_mode: Record<string, number> }>(
    `/admin/analytics/errors`);

export const getLatencyAnalytics = () =>
  api<{ stages: Record<string, { n: number; p50_ms: number; p95_ms: number }>; total: number }>(
    `/admin/analytics/latency`);

export const documentPreview = (sid: string, body: { doc_type: string; branding?: Record<string, string> }) =>
  api<RenderedDocument>(`/sessions/${sid}/document/preview`, jsonBody(body));

export const updateDocument = (docId: string, body: { edited_html: string }) =>
  api<RenderedDocument>(`/documents/${docId}`, { ...jsonBody(body), method: 'PUT' });

export const approveDocument = (docId: string) =>
  api<RenderedDocument>(`/documents/${docId}/approve`, { method: 'POST' });

export const listSessionDocuments = (sid: string) => api<RenderedDocument[]>(`/sessions/${sid}/documents`);

export const getFeatureFlags = () =>
  api<{ config: Record<string, any>; runtime: { key: string; enabled: boolean; value: any }[] }>('/feature-flags');

export const setFeatureFlag = (body: { key: string; enabled: boolean }) =>
  api<{ key: string; enabled: boolean }>('/feature-flags', jsonBody(body));
