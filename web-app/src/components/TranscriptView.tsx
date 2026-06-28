import { useMemo, useState } from 'react';
import { useStore } from '../store';
import type { Segment } from '../api';

// Two distinct transcripts, never one replacing the other:
//   • Raw   — verbatim Sarvam output, speakers shown as anonymous "Speaker 1 / Speaker 2"
//             from the diarization (no clinical-role guessing).
//   • Tuned — the LLM-cleaned transcript, speakers shown as Doctor / Patient.
// While recording, Sarvam streaming returns no speaker separation, so the live transcript is
// plain text with NO speaker chip (real labels only exist after Stop, from the diarized pass).

function capitalize(s: string) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

export function TranscriptView() {
  const s = useStore();
  const [view, setView] = useState<'raw' | 'tuned'>('tuned');

  const rawSegs = s.raw?.segments ?? [];
  const cleanSegs = s.clean?.segments ?? [];
  const hasRaw = rawSegs.length > 0;
  const hasTuned = cleanSegs.length > 0;
  const liveOnly = !hasRaw && !hasTuned;

  // Anonymous speaker numbering for the raw view, keyed by the provider's diarization label
  // (falling back to the role/unknown when a recording had no diarization).
  const speakerNo = useMemo(() => {
    const m = new Map<string, number>();
    let n = 0;
    for (const seg of rawSegs) {
      const key = seg.diarized_label || seg.speaker || 'unknown';
      if (!m.has(key)) m.set(key, ++n);
    }
    return m;
  }, [rawSegs]);

  // Recover the clinical role for the tuned view by segment id from the raw transcript —
  // the LLM clean step focuses on text and may not echo the speaker field, but segment ids
  // are kept stable across raw and clean, so this guarantees Doctor/Patient labels.
  const roleById = useMemo(() => {
    const m = new Map<string, string>();
    for (const seg of rawSegs) m.set(seg.id, seg.speaker);
    return m;
  }, [rawSegs]);

  const low = useMemo(() => new Set(s.clean?.low_confidence_span_ids || []), [s.clean]);

  // ── Live: plain text, no speaker chip ──────────────────────────────────────
  if (liveOnly) {
    const liveSegs = s.segments;
    return (
      <div className="card">
        <h2>Transcript {s.recording && <span className="kv">· live</span>}</h2>
        {liveSegs.length ? (
          <div className="transcript-live">
            {liveSegs.map((x) => (
              <p key={x.span_id} className="transcript-live-line">{x.text}</p>
            ))}
          </div>
        ) : (
          <p className="muted">{s.recording ? 'Listening…' : 'No transcript.'}</p>
        )}
      </div>
    );
  }

  // ── After Stop: Raw (Speaker 1/2) ⇄ Tuned (Doctor/Patient) ──────────────────
  const effective: 'raw' | 'tuned' = !hasTuned ? 'raw' : !hasRaw ? 'tuned' : view;
  const segs: Segment[] = effective === 'raw' ? rawSegs : cleanSegs;

  const tunedRole = (seg: Segment) => roleById.get(seg.id) || seg.speaker || 'unknown';

  const label = (seg: Segment) =>
    effective === 'raw'
      ? `Speaker ${speakerNo.get(seg.diarized_label || seg.speaker || 'unknown') ?? 1}`
      : capitalize(tunedRole(seg));

  // Raw speakers are anonymous → neutral chip; tuned uses the role-coloured chip.
  const whoClass = (seg: Segment) =>
    effective === 'raw' ? 'who other' : `who ${tunedRole(seg)}`;

  return (
    <div className="card">
      <div className="transcript-head">
        <h2>Transcript</h2>
        {hasRaw && hasTuned && (
          <div className="seg-theme" role="tablist" aria-label="Transcript version">
            <button className={effective === 'raw' ? 'active' : ''} onClick={() => setView('raw')}>Raw</button>
            <button className={effective === 'tuned' ? 'active' : ''} onClick={() => setView('tuned')}>Tuned</button>
          </div>
        )}
      </div>

      <p className="kv">
        {effective === 'raw'
          ? 'Verbatim speech-to-text, anonymous speakers.'
          : s.clean?.corrections?.length
          ? `LLM-cleaned · ${s.clean.corrections.length} STT correction(s) applied; low-confidence spans highlighted.`
          : 'LLM-cleaned transcript.'}
      </p>

      {segs.map((x) => (
        <div className="seg" key={x.id}>
          <span className={whoClass(x)}>{label(x)}</span>
          <div>
            <span className={low.has(x.id) ? 'lowconf' : ''}>{x.text}</span>
            <div className="kv">{x.id} · conf {(x.confidence ?? 1).toFixed(2)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
