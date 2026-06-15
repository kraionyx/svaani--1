import { useEffect, useRef } from 'react';
import { useStore } from '../store';

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
  const segments = useStore((s) => s.segments);

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
    <div className="recorder-panel">
      <div style={{ flexGrow: 1 }}></div>

      { p.recording || p.busy ? (
        <div className="spotify-lyrics-container">
          {p.busy && !p.recording ? (
            <div className="processing-state">
               <div className="spinner"></div>
               <h3>{p.stage || 'Processing consultation...'}</h3>
            </div>
          ) : (
             <div className="lyrics-scroll">
                {segments.map((seg, i) => (
                   <span key={seg.id || i} className={`lyric-txt ${seg.is_final ? 'final' : 'active'}`}>
                     {seg.text}{' '}
                     {seg.is_final === false && <span className="caret">_</span>}
                   </span>
                ))}
             </div>
          )}
        </div>
      ) : (
        <div className="templates-grid">
          {p.templates.map((t) => (
            <button 
              key={t.template_id} 
              className={`doc-icon ${p.templateId === t.template_id ? 'active' : ''}`}
              onClick={() => p.onTemplate(t.template_id)}
              disabled={p.busy}
            >
              <div className="doc-preview">
                <div className="line"></div>
                <div className="line"></div>
                <div className="line half"></div>
              </div>
              <span className="doc-name">{t.name}</span>
            </button>
          ))}
        </div>
      )}



      <div style={{ flexGrow: 1 }}></div>

      <div className="record-controls-row">
        <input ref={fileRef} type="file" accept="audio/*" style={{ display: 'none' }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onUpload(f); e.currentTarget.value = ''; }} />
        <button className="icon-btn" disabled={p.busy} onClick={() => fileRef.current?.click()} title="Upload audio">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
        </button>
        
        <button className={`pill-btn ${p.recording ? 'danger' : 'primary'}`} onClick={p.onRecord} disabled={p.busy && !p.recording}>
          {p.recording ? '■ Stop & finalize' : '● Start Recording'}
        </button>

        <button className="icon-btn" disabled={p.busy} onClick={p.onSimulate} title="Simulate">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        </button>
      </div>
    </div>
  );
}
