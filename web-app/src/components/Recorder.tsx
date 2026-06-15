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
  const fileRef = useRef<HTMLInputElement>(null);
  const segments = useStore((s) => s.segments);

  const scrollRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
    }
  }, [segments]);

  useEffect(() => {
    if (!p.analyser || !p.recording) return;
    const data = new Uint8Array(p.analyser.frequencyBinCount);
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      p.analyser!.getByteFrequencyData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i];
      const avg = sum / data.length;
      if (glowRef.current) {
        const intensity = avg / 255;
        glowRef.current.style.opacity = `${0.3 + intensity * 0.7}`;
        glowRef.current.style.transform = `scaleY(${1 + intensity})`;
      }
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [p.analyser, p.recording]);

  return (
    <>
      { (p.recording || p.busy) && (
        <div ref={glowRef} className="aurora-glow"></div>
      )}
      <div className="recorder-panel" style={{ zIndex: 1, position: 'relative' }}>
        <div style={{ flexGrow: 1 }}></div>

      { p.recording || p.busy ? (
        <div className="spotify-lyrics-container">
          {p.busy && !p.recording ? (
            <div className="processing-state">
               <div className="spinner"></div>
               <h3>{p.stage || 'Processing consultation...'}</h3>
            </div>
          ) : (
             <div style={{ position: 'relative', width: '100%', height: '100%', display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                 <div className="lyrics-scroll" ref={scrollRef} style={{ zIndex: 1, position: 'relative', paddingBottom: '80px' }}>
                    {segments.map((seg, i) => (
                       <span key={seg.span_id || i} className={`lyric-txt ${seg.final ? 'final' : 'active'}`}>
                         {seg.text}{' '}
                         {seg.final === false && <span className="caret">_</span>}
                       </span>
                    ))}
                 </div>
             </div>
          )}
        </div>
      ) : (
        <div className="templates-container" style={{ position: 'relative', width: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
          <h2 style={{ position: 'absolute', top: '-100px', fontSize: '1.8rem', fontWeight: 'bold', color: 'gray', margin: 0, textAlign: 'center', width: '100%' }}>Choose Template</h2>
          <div className="templates-grid" style={{ margin: 0 }}>
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
    </>
  );
}
