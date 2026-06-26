import { useEffect, useRef, useState } from 'react';

interface Props {
  recording: boolean; paused: boolean; busy: boolean; streaming: boolean; stage: string;
  templates: { template_id: string; name: string }[]; templateId: string;
  onTemplate: (t: string) => void;
  onRecord: () => void; onSimulate: () => void; onUpload: (f: File) => void;
  onPause: () => void; onCancel: () => void;
  analyser: AnalyserNode | null;
  modeChoice: 'realtime' | 'batch' | 'auto' | 'hybrid';
  onModeChoice: (v: 'realtime' | 'batch' | 'auto' | 'hybrid') => void;
}

type ModeId = 'realtime' | 'hybrid' | 'batch' | 'auto';
const MODE_OPTIONS: { id: ModeId; label: string }[] = [
  { id: 'realtime', label: 'Real-time' },
  { id: 'hybrid', label: 'Hybrid' },
  { id: 'batch', label: 'Batch' },
  { id: 'auto', label: 'Auto' },
];
const MODE_HINT: Record<ModeId, string> = {
  realtime: 'Fastest — note streams live; no speaker separation.',
  hybrid: 'Best balance — instant draft, then always sharpens to full speaker-labeled accuracy.',
  batch: 'Most accurate — full speaker labels; note is produced after you stop.',
  auto: 'AI decides — keeps the live draft for simple consults, sharpens only when complex.',
};

function fmtTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

export function Recorder(p: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (!p.recording) { setElapsed(0); return; }
    if (p.paused) return;
    timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [p.recording, p.paused]);

  // Waveform: a *real* audio visualiser driven by the mic's time-domain data — NOT a
  // canned animation. When silent the samples sit at ~128 so the line is flat; it only
  // moves when there's actual sound. Idle (not recording) and Paused draw a static flat
  // baseline with no animation loop at all, so the graphic never "flows" without audio.
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext('2d');
    if (!ctx) return;
    let raf = 0;

    const isLive = p.recording && !p.paused && !!p.analyser;
    const timeData = p.analyser ? new Uint8Array(p.analyser.fftSize) : null;

    // Crisp on HiDPI; only resizes the backing store when the box actually changes.
    const dims = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = cv.clientWidth || 280;
      const h = cv.clientHeight || 48;
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
        cv.width = Math.round(w * dpr);
        cv.height = Math.round(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { w, h };
    };

    const accent = () => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#1ec7b1';
    const RECORD_COLOR = '#e74c3c';

    // Static baseline — no requestAnimationFrame, so it cannot animate without audio.
    const drawFlat = () => {
      const { w, h } = dims();
      ctx.clearRect(0, 0, w, h);
      ctx.lineWidth = 2;
      ctx.lineCap = 'round';
      ctx.globalAlpha = p.paused ? 0.55 : 0.3;
      ctx.strokeStyle = p.paused ? RECORD_COLOR : accent();
      ctx.beginPath();
      ctx.moveTo(3, h / 2);
      ctx.lineTo(w - 3, h / 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
    };

    // Live mic waveform from real samples — flat at silence, reactive when you speak.
    const drawLive = () => {
      raf = requestAnimationFrame(drawLive);
      if (!p.analyser || !timeData) return;
      const { w, h } = dims();
      ctx.clearRect(0, 0, w, h);
      p.analyser.getByteTimeDomainData(timeData);

      const mid = h / 2;
      const maxAmp = mid - 3;
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.strokeStyle = RECORD_COLOR;
      ctx.globalAlpha = 0.95;
      ctx.beginPath();
      const step = timeData.length / w;
      for (let x = 0; x < w; x++) {
        const sample = (timeData[Math.floor(x * step)] - 128) / 128; // -1..1; 0 == silence
        const envelope = Math.sin((x / w) * Math.PI);                 // taper at both ends
        const y = mid + sample * maxAmp * envelope;
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    };

    if (isLive) drawLive(); else drawFlat();
    return () => cancelAnimationFrame(raf);
  }, [p.analyser, p.recording, p.paused]);

  return (
    <div className="card panel">
      <div className="step-h"><span className="n">1</span><h3>Capture</h3></div>
      <label className="lbl">Template</label>
      <select value={p.templateId} disabled={p.busy} onChange={(e) => p.onTemplate(e.target.value)}>
        {p.templates.map((t) => <option key={t.template_id} value={t.template_id}>{t.name}</option>)}
      </select>

      <div className={`mic-wrap ${p.recording ? 'live' : ''}`}>
        <canvas ref={canvasRef} className="mic-canvas" />
        <div className="mic-status">
          {p.recording ? (p.paused
            ? <b style={{ color: 'var(--warn, #e0a500)' }}>Paused — {fmtTime(elapsed)}</b>
            : <b>Listening… {p.streaming ? '(streaming live)' : ''} <span style={{ fontVariantNumeric: 'tabular-nums', marginLeft: 6 }}>{fmtTime(elapsed)}</span></b>)
            : p.busy ? <b>{p.stage || 'Processing'}…</b>
              : 'Ready — press record to start.'}
        </div>
      </div>

      <label className="lbl">Inference mode</label>
      <div className="mode-seg" role="group" aria-label="Inference mode">
        {MODE_OPTIONS.map((m) => (
          <button
            key={m.id}
            type="button"
            className={p.modeChoice === m.id ? 'active' : ''}
            disabled={p.recording || p.busy}
            onClick={() => p.onModeChoice(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>
      <p className="hint" style={{ marginTop: 6 }}>{MODE_HINT[p.modeChoice]}</p>

      <button className={`btn big ${p.recording ? 'danger' : ''}`} onClick={p.onRecord} disabled={p.busy && !p.recording}>
        {p.recording ? '■ Stop & finalize' : '● Record consultation'}
      </button>

      {p.recording && (
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn ghost sm" onClick={p.onPause} style={{ flex: 1 }}>
            {p.paused ? '▶ Resume' : '❚❚ Pause'}
          </button>
          <button className="btn ghost sm danger" onClick={p.onCancel} style={{ flex: 1 }}>
            ✕ Cancel
          </button>
        </div>
      )}

      <div className="row">
        <input ref={fileRef} type="file" accept="audio/*" style={{ display: 'none' }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onUpload(f); e.currentTarget.value = ''; }} />
        <button className="btn ghost sm" disabled={p.busy || p.recording} onClick={() => fileRef.current?.click()}>Upload audio</button>
        <button className="btn ghost sm" disabled={p.busy || p.recording} onClick={p.onSimulate}>▶ Simulate</button>
      </div>
      <p className="hint">Record uses real-time streaming STT; on stop, the consult is diarized and the note streams in.</p>
    </div>
  );
}
