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
  variant?: 'sidebar' | 'center';
}

type ModeId = 'realtime' | 'hybrid' | 'batch' | 'auto';
const MODE_OPTIONS: { id: ModeId; label: string }[] = [
  { id: 'realtime', label: 'Real-time' },
  { id: 'hybrid', label: 'Hybrid' },
  { id: 'batch', label: 'Batch' },
  { id: 'auto', label: 'Auto' },
];


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

    const accent = () => '#38bdf8'; // sky-400
    const RECORD_COLOR = '#0ea5e9'; // sky-500

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
  }, [p.analyser, p.recording, p.paused, p.variant]);

  if (p.variant === 'center') {
    return (
      <div className="flex flex-col items-center w-full transition-all duration-700 ease-in-out transform opacity-100 scale-100">
        <div className="flex items-center bg-white shadow-lg shadow-sky-900/5 rounded-[2rem] border border-slate-200/60 p-2.5 w-full max-w-3xl gap-3">
          
          <div className="relative flex-1">
            <select 
              value={p.templateId} 
              disabled={p.busy} 
              onChange={(e) => p.onTemplate(e.target.value)}
              className="appearance-none bg-slate-50 border border-slate-200 hover:border-sky-200 rounded-full pl-5 pr-10 py-3.5 text-sm font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-100 focus:bg-white w-full cursor-pointer transition-colors"
            >
              {p.templates.map((t) => <option key={t.template_id} value={t.template_id}>{t.name}</option>)}
            </select>
            <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </div>
          </div>

          <div className="relative flex-1">
            <select
              value={p.modeChoice}
              disabled={p.recording || p.busy}
              onChange={(e) => p.onModeChoice(e.target.value as any)}
              className="appearance-none bg-slate-50 border border-slate-200 hover:border-sky-200 rounded-full pl-5 pr-10 py-3.5 text-sm font-medium text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-100 focus:bg-white w-full cursor-pointer transition-colors"
            >
              {MODE_OPTIONS.map((m) => <option key={m.id} value={m.id}>{m.label} Mode</option>)}
            </select>
            <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </div>
          </div>

          <button 
            className="w-14 h-14 rounded-full flex items-center justify-center transition-all shadow-md shadow-sky-500/20 flex-shrink-0 bg-sky-500 hover:bg-sky-600 hover:scale-105 active:scale-95 text-white"
            onClick={p.onRecord} 
            disabled={p.busy && !p.recording}
            title="Start consultation"
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" x2="12" y1="19" y2="22"></line></svg>
          </button>
        </div>

        <div className="flex items-center gap-6 mt-6 opacity-70">
           <input ref={fileRef} type="file" accept="audio/*" style={{ display: 'none' }} onChange={(e) => { const f = e.target.files?.[0]; if (f) p.onUpload(f); e.currentTarget.value = ''; }} />
           <button className="text-[13px] font-medium text-slate-500 hover:text-slate-800 transition-colors flex items-center gap-2" disabled={p.busy || p.recording} onClick={() => fileRef.current?.click()}>
             <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/></svg>
             Upload Audio
           </button>
           <span className="text-slate-300">•</span>
           <button className="text-[13px] font-medium text-slate-500 hover:text-slate-800 transition-colors flex items-center gap-2" disabled={p.busy || p.recording} onClick={p.onSimulate}>
             <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
             Simulate Session
           </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 mb-1 opacity-80">
        <span className="flex items-center justify-center w-6 h-6 rounded-full bg-sky-100 text-sky-600 text-xs font-bold">1</span>
        <h3 className="text-[11px] font-bold tracking-[1.5px] text-slate-500 uppercase">Capture</h3>
      </div>

      <div className={`relative overflow-hidden border rounded-xl p-4 bg-gradient-to-b from-sky-50/50 to-white transition-all duration-300 ${p.recording ? 'border-sky-400 shadow-[0_0_0_3px_rgba(56,189,248,0.2)]' : 'border-slate-200'}`}>
        <canvas ref={canvasRef} className="w-full h-12 block relative z-10" />
        <div className="text-xs text-slate-500 mt-2 min-h-[16px]">
          {p.recording ? (p.paused
            ? <b className="text-amber-500 font-bold">Paused — {fmtTime(elapsed)}</b>
            : <b className="text-sky-600 font-bold">Listening… {p.streaming ? '(streaming live)' : ''} <span className="tabular-nums ml-1.5">{fmtTime(elapsed)}</span></b>)
            : p.busy ? <b className="text-sky-600 font-bold">{p.stage || 'Processing'}…</b>
              : 'Session captured.'}
        </div>
      </div>

      {p.recording && (
        <div className="flex flex-col mt-2 gap-2">
          <button 
            className="w-full py-3.5 rounded-xl text-[14px] font-bold shadow-md shadow-sky-500/20 text-white bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 transition-all active:scale-[0.98]" 
            onClick={p.onRecord} 
            disabled={p.busy && !p.recording}
          >
            ■ Stop & finalize
          </button>
          
          <div className="flex gap-2">
            <button className="flex-1 py-2.5 rounded-xl text-[13px] font-semibold text-slate-600 bg-slate-100 hover:bg-slate-200 transition-colors active:scale-[0.98]" onClick={p.onPause}>
              {p.paused ? '▶ Resume' : '❚❚ Pause'}
            </button>
            <button className="flex-1 py-2.5 rounded-xl text-[13px] font-semibold text-slate-600 bg-slate-100 hover:bg-red-50 hover:text-red-600 transition-colors active:scale-[0.98]" onClick={p.onCancel}>
              ✕ Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
