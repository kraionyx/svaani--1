import { create } from 'zustand';
import type { Extraction, Grounding, Note, RawTranscript, CleanTranscript, Risk, ReviewState } from './api';

export interface LiveSegment { speaker: string; text: string; span_id: string; final?: boolean; }
export interface LiveNoteSection { label: string; text: string; done: boolean; }

interface AppState {
  health: { sarvam: string; vertex: string } | null;
  templates: { template_id: string; name: string }[];
  templateId: string;
  role: string;
  modeChoice: 'realtime' | 'batch' | 'auto' | 'hybrid';   // Goal 3: per-consult pre-recording mode pick
  sessionId: string | null;
  reviewState: ReviewState | null;
  stage: string;
  streaming: boolean;
  recording: boolean;
  paused: boolean;
  busy: boolean;
  activeTab: string;

  segments: LiveSegment[];
  liveNote: Record<string, LiveNoteSection>;
  liveNoteOrder: string[];

  note: Note | null;
  extraction: Extraction | null;
  risk: Risk | null;
  grounding: Grounding | null;
  raw: RawTranscript | null;
  clean: CleanTranscript | null;

  // Intelligence (Goals 1-5)
  confidenceBand: 'high' | 'moderate' | 'low' | null;
  confidenceReasons: string[];
  modeNotice: { from: string; to: string; reason: string; est_delay_s: number[] } | null;
  reviewSubmitted: boolean;

  history: import('./api').SessionSummary[];

  set: (p: Partial<AppState>) => void;
  resetSession: () => void;
  addSegment: (s: LiveSegment) => void;
  replaceSegments: (segs: LiveSegment[]) => void;
  noteChunk: (c: { section_id: string; label?: string; delta?: string; start?: boolean; done?: boolean }) => void;
  loadHistory: () => Promise<void>;
  loadOutputs: (sid: string) => Promise<void>;
  openSession: (sid: string) => Promise<void>;
}

export const useStore = create<AppState>((set) => ({
  health: null,
  templates: [],
  templateId: 'ent',
  role: localStorage.getItem('svaani-role') || 'doctor',
  modeChoice: (localStorage.getItem('svaani-mode') as 'realtime' | 'batch' | 'auto' | 'hybrid') || 'realtime',
  sessionId: null,
  reviewState: null,
  stage: '',
  streaming: false,
  recording: false,
  paused: false,
  busy: false,
  activeTab: 'note',

  segments: [],
  liveNote: {},
  liveNoteOrder: [],

  note: null,
  extraction: null,
  risk: null,
  grounding: null,
  raw: null,
  clean: null,

  confidenceBand: null,
  confidenceReasons: [],
  modeNotice: null,
  reviewSubmitted: false,
  history: [],

  set: (p) => set(p),
  resetSession: () => set({
    sessionId: null, reviewState: null, stage: '', streaming: false, paused: false, segments: [],
    liveNote: {}, liveNoteOrder: [], note: null, extraction: null, risk: null,
    grounding: null, raw: null, clean: null,
    confidenceBand: null, confidenceReasons: [], modeNotice: null, reviewSubmitted: false,
  }),
  addSegment: (s) => set((st) => {
    if (s.final) {
      const kept = st.segments.filter((x) => x.final);
      return { segments: [...kept, s] };
    }
    return { segments: [...st.segments, s] };
  }),
  replaceSegments: (segs) => set({ segments: segs }),
  noteChunk: (c) => set((st) => {
    const live = { ...st.liveNote };
    const order = st.liveNoteOrder.includes(c.section_id) ? st.liveNoteOrder : [...st.liveNoteOrder, c.section_id];
    const cur = live[c.section_id] || { label: c.label || c.section_id, text: '', done: false };
    if (c.start) live[c.section_id] = { label: c.label || cur.label, text: '', done: false };
    else if (c.done) live[c.section_id] = { ...cur, done: true };
    else if (c.delta) live[c.section_id] = { ...cur, text: cur.text + c.delta };
    return { liveNote: live, liveNoteOrder: order };
  }),
  loadHistory: async () => {
    try {
      const hist = await import('./api').then(api => api.listSessions());
      set({ history: hist });
    } catch (e) { /* ignore */ }
  },
  loadOutputs: async (sid: string) => {
    try {
      const API = await import('./api');
      const [note, risk, extraction, raw, clean] = await Promise.all(
        ['note', 'risk', 'extraction', 'raw', 'clean'].map((k) => API.getOutput(sid, k).catch(() => null))
      );
      set({ note, risk, extraction, raw, clean });
      if (raw && raw.segments && Array.isArray(raw.segments)) {
        const mapped = raw.segments.map((x: any) => ({
          speaker: x.speaker || 'unknown',
          text: x.text || '',
          span_id: x.id || x.span_id || `legacy-${Math.random()}`,
          final: true,
        }));
        set({ segments: mapped });
      }
    } catch (e) {}
  },
  openSession: async (sid: string) => {
    const API = await import('./api');
    const toast = await import('./toast').then(m => m.toast);
    try {
      useStore.getState().resetSession();
      const meta: any = await API.api(`/sessions/${sid}`);
      set({ sessionId: sid, reviewState: meta.state, activeTab: 'note' });
      await useStore.getState().loadOutputs(sid);
    } catch (e: any) { toast(e.message || 'could not open consultation', true); }
  }
}));
