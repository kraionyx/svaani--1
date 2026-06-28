// Microphone capture → 16 kHz mono PCM16 chunks, for streaming over the WebSocket.
// Also exposes a WAV encoder for the REST upload fallback.

const TARGET_RATE = 16000;

export interface MicHandle {
  stop: () => Promise<Int16Array>;   // resolves with the full captured 16 kHz PCM16
  pause: () => void;                 // stop capturing/streaming audio (paused segment is dropped)
  resume: () => void;                // resume capturing/streaming
  isPaused: () => boolean;
  analyser: AnalyserNode;
}

export function micSupported(): boolean {
  return !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
}

function clampToPcm16(s: number): number {
  s = Math.max(-1, Math.min(1, s));
  return s < 0 ? s * 0x8000 : s * 0x7fff;
}

function floatTo16k(float: Float32Array, inRate: number): Int16Array {
  // Fast path: the AudioContext is already running at 16 kHz (the browser's high-quality
  // resampler did the work), so this is a straight float → PCM16 conversion with no
  // resampling and therefore no aliasing.
  if (inRate === TARGET_RATE) {
    const out = new Int16Array(float.length);
    for (let i = 0; i < float.length; i++) out[i] = clampToPcm16(float[i]);
    return out;
  }
  // Fallback (a browser that ignored the 16 kHz hint, e.g. older Safari): average each
  // source window instead of picking every Nth sample. A box average is a crude low-pass
  // that suppresses the alias noise the old nearest-neighbour decimation folded into the
  // speech band — degraded STT accuracy was traced to that aliasing.
  const ratio = inRate / TARGET_RATE;
  const outLen = Math.floor(float.length / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(float.length, Math.floor((i + 1) * ratio));
    let sum = 0, n = 0;
    for (let j = start; j < end; j++) { sum += float[j]; n++; }
    out[i] = clampToPcm16(n ? sum / n : 0);
  }
  return out;
}

/**
 * Start capturing the mic. `onChunk` receives ~250ms of 16 kHz PCM16 as it is captured
 * (for live streaming). The returned `stop()` resolves with the entire recording.
 */
export async function startMic(onChunk: (pcm: Int16Array) => void): Promise<MicHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  // Ask the browser to run the graph at 16 kHz so its high-quality resampler handles the
  // 48k→16k conversion (Sarvam needs 16 kHz mono PCM16). This replaces the old approach of
  // running at the hardware rate (~48 kHz) and naively decimating 3:1 — that folded
  // high-frequency energy back into the speech band as aliasing noise and hurt STT accuracy.
  // Most current browsers honour the hint; if one doesn't, floatTo16k() average-decimates.
  let ctx: AudioContext;
  try { ctx = new AudioContext({ sampleRate: TARGET_RATE }); }
  catch { ctx = new AudioContext(); }
  if (ctx.state === 'suspended') await ctx.resume();
  const src = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser(); analyser.fftSize = 256; src.connect(analyser);

  const collected: Int16Array[] = [];
  let pending: Float32Array[] = [];
  let pendingLen = 0;
  let paused = false;
  const flushEvery = Math.floor(ctx.sampleRate * 0.25); // ~250ms

  const onFrame = (frame: Float32Array) => {
    // While paused, drop frames entirely — neither streamed nor kept in the final buffer,
    // so the paused interval simply doesn't exist in the recording.
    if (paused) return;
    pending.push(frame); pendingLen += frame.length;
    if (pendingLen >= flushEvery) {
      const merged = new Float32Array(pendingLen); let o = 0;
      for (const f of pending) { merged.set(f, o); o += f.length; }
      pending = []; pendingLen = 0;
      const pcm = floatTo16k(merged, ctx.sampleRate);
      collected.push(pcm); onChunk(pcm);
    }
  };

  // AudioWorklet only — the deprecated ScriptProcessorNode is intentionally not used.
  // (AudioWorklet is supported across all current browsers; we fail clearly otherwise.)
  if (!ctx.audioWorklet) {
    await ctx.close(); stream.getTracks().forEach((t) => t.stop());
    throw new Error('This browser does not support AudioWorklet — please use a current browser.');
  }
  const code = "class P extends AudioWorkletProcessor{process(i){const c=i[0][0];if(c)this.port.postMessage(c.slice(0));return true;}}registerProcessor('pcm',P);";
  const url = URL.createObjectURL(new Blob([code], { type: 'application/javascript' }));
  await ctx.audioWorklet.addModule(url); URL.revokeObjectURL(url);
  const worklet = new AudioWorkletNode(ctx, 'pcm');
  worklet.port.onmessage = (e) => onFrame(new Float32Array(e.data));
  src.connect(worklet); worklet.connect(ctx.destination);

  const stop = async (): Promise<Int16Array> => {
    if (pendingLen > 0) {
      const merged = new Float32Array(pendingLen); let o = 0;
      for (const f of pending) { merged.set(f, o); o += f.length; }
      const pcm = floatTo16k(merged, ctx.sampleRate); collected.push(pcm);
    }
    worklet.disconnect(); analyser.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    await ctx.close();
    const total = collected.reduce((a, b) => a + b.length, 0);
    const all = new Int16Array(total); let off = 0;
    for (const c of collected) { all.set(c, off); off += c.length; }
    return all;
  };

  const pause = () => {
    // Flush whatever is buffered so a partial chunk isn't carried across the pause boundary.
    if (pendingLen > 0) {
      const merged = new Float32Array(pendingLen); let o = 0;
      for (const f of pending) { merged.set(f, o); o += f.length; }
      pending = []; pendingLen = 0;
      const pcm = floatTo16k(merged, ctx.sampleRate);
      collected.push(pcm); onChunk(pcm);
    }
    paused = true;
  };
  const resume = () => { paused = false; };
  const isPaused = () => paused;

  return { stop, pause, resume, isPaused, analyser };
}

/** Wrap 16 kHz PCM16 in a WAV container (for the REST upload fallback). */
export function pcm16ToWav(pcm: Int16Array, rate = TARGET_RATE): Blob {
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const v = new DataView(buf);
  const wr = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  wr(0, 'RIFF'); v.setUint32(4, 36 + pcm.length * 2, true); wr(8, 'WAVE'); wr(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); wr(36, 'data'); v.setUint32(40, pcm.length * 2, true);
  let o = 44; for (let i = 0; i < pcm.length; i++) { v.setInt16(o, pcm[i], true); o += 2; }
  return new Blob([buf], { type: 'audio/wav' });
}
