import { useStore } from '../store';

export function TranscriptView() {
  const s = useStore();
  // Prefer the final diarized transcript once available; otherwise show the live stream.
  const low = new Set(s.clean?.low_confidence_span_ids || []);
  const segs = s.raw?.segments?.length
    ? s.raw.segments.map((x) => ({ speaker: x.speaker, text: x.text, id: x.id, conf: x.confidence, low: low.has(x.id) }))
    : s.segments.map((x) => ({ speaker: x.speaker, text: x.text, id: x.span_id, conf: 1, low: false }));

  const liveBadge = s.recording && !s.raw;
  return (
    <div className="card">
      <h2>Transcript {liveBadge && <span className="kv">· live</span>}</h2>
      {s.clean?.corrections?.length ? <p className="kv">{s.clean.corrections.length} STT correction(s) applied; low-confidence spans highlighted.</p> : null}
      {segs.length ? segs.map((x) => (
        <div className="seg" key={x.id}>
          <span className={`who ${x.speaker}`}>{x.speaker}</span>
          <div>
            <span className={x.low ? 'lowconf' : ''}>{x.text}</span>
            <div className="kv">{x.id} · conf {x.conf.toFixed(2)}</div>
          </div>
        </div>
      )) : <p className="muted">{s.recording ? 'Listening…' : 'No transcript.'}</p>}
    </div>
  );
}
