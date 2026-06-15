import { create } from 'zustand';
import type { Extraction, Grounding, Note, RawTranscript, CleanTranscript, Risk, ReviewState } from './api';

export interface LiveSegment { speaker: string; text: string; span_id: string; final?: boolean; }
export interface LiveNoteSection { label: string; text: string; done: boolean; }

interface AppState {
  health: { sarvam: string; vertex: string } | null;
  templates: { template_id: string; name: string }[];
  templateId: string;
  role: string;
  sessionId: string | null;
  reviewState: ReviewState | null;
  stage: string;
  streaming: boolean;
  recording: boolean;
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

  set: (p: Partial<AppState>) => void;
  resetSession: () => void;
  addSegment: (s: LiveSegment) => void;
  replaceSegments: (segs: LiveSegment[]) => void;
  noteChunk: (c: { section_id: string; label?: string; delta?: string; start?: boolean; done?: boolean }) => void;
}

export const useStore = create<AppState>((set) => ({
  health: null,
  templates: [],
  templateId: 'ent',
  role: localStorage.getItem('svaani-role') || 'doctor',
  sessionId: null,
  reviewState: null,
  stage: '',
  streaming: false,
  recording: false,
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

  set: (p) => set(p),
  resetSession: () => set({
    sessionId: null, reviewState: null, stage: '', streaming: false, segments: [],
    liveNote: {}, liveNoteOrder: [], note: null, extraction: null, risk: null,
    grounding: null, raw: null, clean: null,
    confidenceBand: null, confidenceReasons: [], modeNotice: null, reviewSubmitted: false,
  }),
  addSegment: (s) => set((st) => {
    // A `final` segment replaces the live (unlabeled) view with the diarized one.
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
}));
