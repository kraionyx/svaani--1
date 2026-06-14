import { useEffect, useRef } from 'react';

interface Props {
  recording: boolean; busy: boolean; streaming: boolean; stage: string;
  templates: { template_id: string; name: string }[]; templateId: string;
  onTemplate: (t: string) => void;
  onRecord: () => void; onSimulate: () => void; onUpload: (f: File) => void;
  analyser: AnalyserNode | null;
}

export function Recorder(p: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!p.analyser || !p.recording) return;
    const cv = canvasRef.current!; const ctx = cv.getContext('2d')!;
    const data = new Uint8Array(p.analyser.frequencyBinCount);
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const w = cv.width = cv.clientWidth || 280; const h = cv.height = 46;
      ctx.clearRect(0, 0, w, h);
      p.analyser!.getByteFrequencyData(data);
      const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#0fb9a6';
      ctx.fillStyle = accent;
      const bars = 40, step = Math.max(1, Math.floor(data.length / bars)), bw = w / bars;
      for (let i = 0; i < bars; i++) { const v = data[i * step] / 255; const bh = Math.max(2, v * h * 0.95); ctx.fillRect(i * bw + 1, (h - bh) / 2, bw - 2, bh); }
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
