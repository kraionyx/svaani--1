import { useEffect, useRef } from 'react';

interface Props {
  recording: boolean; busy: boolean; streaming: boolean; stage: string;
  templates: { template_id: string; name: string }[]; templateId: string;
  onTemplate: (t: string) => void;
  onRecord: () => void; onSimulate: () => void; onUpload: (f: File) => void;
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

export function Recorder(p: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const cv = canvasRef.current!; const ctx = cv.getContext('2d')!;
    let raf = 0;
    const data = p.analyser ? new Uint8Array(p.analyser.frequencyBinCount) : null;

    const draw = () => {
      raf = requestAnimationFrame(draw);
      const w = cv.width = cv.clientWidth || 280; const h = cv.height = 46;
      ctx.clearRect(0, 0, w, h);

      let intensity = 0.1; // Default breathing intensity
      if (p.analyser && p.recording && data) {
        p.analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
          sum += data[i];
        }
        intensity = (sum / data.length) / 128.0;
      }

      const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#0fb9a6';
      
      const numWaves = 3;
      const phases = [0, Math.PI / 3, Math.PI * 2 / 3];
      const opacities = p.recording ? [0.8, 0.4, 0.2] : [0.35, 0.2, 0.1];
      const speeds = p.recording ? [0.18, 0.12, 0.08] : [0.03, 0.02, 0.015];
      const time = performance.now() * 0.01;

      for (let wIndex = 0; wIndex < numWaves; wIndex++) {
        ctx.beginPath();
        ctx.strokeStyle = p.recording ? '#e74c3c' : accent;
        ctx.lineWidth = wIndex === 0 ? 2 : 1;
        ctx.globalAlpha = opacities[wIndex];

        const phase = phases[wIndex] + time * speeds[wIndex];
        const amplitude = (p.recording ? Math.max(5, intensity * 24) : 4) * (wIndex === 0 ? 1.0 : 0.6);

        for (let x = 0; x < w; x++) {
          const normalX = x / w;
          const envelope = Math.sin(normalX * Math.PI);
          const y = h / 2 + Math.sin(normalX * Math.PI * (p.recording ? 3.5 : 2.0) + phase) * amplitude * envelope;
          
          if (x === 0) {
            ctx.moveTo(x, y);
          } else {
            ctx.lineTo(x, y);
          }
        }
        ctx.stroke();
      }
      ctx.globalAlpha = 1.0;
    };

    draw();
    return () => cancelAnimationFrame(raf);
  }, [p.analyser, p.recording]);

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
          {p.recording ? <b>Listening… {p.streaming ? '(streaming live)' : ''}</b>
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

      <div className="row">
        <input ref={fileRef} type="file" accept="audio/*" style={{ display: 'none' }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onUpload(f); e.currentTarget.value = ''; }} />
        <button className="btn ghost sm" disabled={p.busy} onClick={() => fileRef.current?.click()}>Upload audio</button>
        <button className="btn ghost sm" disabled={p.busy} onClick={p.onSimulate}>▶ Simulate</button>
      </div>
      <p className="hint">Record uses real-time streaming STT; on stop, the consult is diarized and the note streams in.</p>
    </div>
  );
}
