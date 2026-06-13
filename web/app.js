/* ============================================================================
   Svaani — AI Medical Scribe frontend.
   Standalone static app: served on its own port (e.g. :5173) and talks to the
   FastAPI backend on :8000. When opened same-origin (the bundled /ui at :8000)
   it uses relative paths instead.
   ========================================================================== */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

// Backend base URL. Same-origin when served by FastAPI (:8000); otherwise :8000.
const API_BASE = (() => {
  const p = location.port;
  if (location.protocol === 'file:') return 'http://127.0.0.1:8000';
  if (p === '' || p === '8000') return '';
  return `${location.protocol}//${location.hostname}:8000`;
})();

let SESSION = null, STATE = null, LASTPROC = null, LASTRAW = null, LASTNOTE = null;
let editing = false;

function headers(extra = {}) {
  return Object.assign({ 'X-User-Id': 'dashboard', 'X-Role': $('#role').value }, extra);
}
function toast(msg, err = false) {
  const t = $('#toast'); t.textContent = msg; t.className = err ? 'err' : '';
  t.style.display = 'block'; clearTimeout(toast._t);
  toast._t = setTimeout(() => t.style.display = 'none', err ? 6500 : 2800);
}
async function api(path, opts = {}) {
  const r = await fetch(API_BASE + path, Object.assign({ headers: headers(opts.headers || {}) }, opts));
  if (!r.ok) { let d; try { d = await r.json(); } catch { d = { detail: r.statusText }; } throw new Error(d.detail || ('HTTP ' + r.status)); }
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : r;
}
function esc(s) { return (s ?? '').toString().replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }

// ---------- theme + role persistence ----------
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem('svaani-theme', t);
  $$('#themeSwitch button').forEach(b => b.classList.toggle('active', b.dataset.theme === t));
}
$$('#themeSwitch button').forEach(b => b.onclick = () => setTheme(b.dataset.theme));
setTheme(localStorage.getItem('svaani-theme') || 'mint');

const savedRole = localStorage.getItem('svaani-role');
if (savedRole) $('#role').value = savedRole;
$('#role').onchange = () => localStorage.setItem('svaani-role', $('#role').value);

// ---------- health + templates ----------
async function loadHealth() {
  try {
    const h = await api('/health');
    const sett = (el, v) => { el.innerHTML = `<span class="d"></span>${el === $('#hSarvam') ? 'STT' : 'LLM'}: ${v}`; el.className = 'pill ' + (v === 'live' ? 'live' : 'mock'); };
    sett($('#hSarvam'), h.sarvam); sett($('#hVertex'), h.vertex);
  } catch (e) { toast('health check failed: ' + e.message + ' — is the backend running on :8000?', true); }
}
async function loadTemplates() {
  const t = await api('/templates'); const sel = $('#template');
  const cur = sel.value;
  sel.innerHTML = t.map(x => `<option value="${esc(x.template_id)}">${esc(x.name)}</option>`).join('');
  if (cur && t.find(x => x.template_id === cur)) sel.value = cur;
  else if (t.find(x => x.template_id === 'ent')) sel.value = 'ent';
}

// ---------- session state ----------
function setState(s) {
  STATE = s; const b = $('#sessState'); b.style.display = 'inline-block';
  b.textContent = s.replace('_', ' '); b.className = 'badge state-' + s;
  const can = { in_review: ['draft', 'edited', 'approved'], approved: ['in_review', 'edited'] };
  $$('[data-state]').forEach(btn => btn.disabled = !(can[btn.dataset.state] || []).includes(s));
  $('#btnFinalize').disabled = (s !== 'approved');
  $$('.ex').forEach(btn => btn.disabled = (s !== 'finalized'));
}
function enableCapture(on) { ['#btnRec', '#file', '#btnUpload', '#btnSim'].forEach(x => $(x).disabled = !on); }
function busy(on) { enableCapture(!on); $('#btnNew').disabled = on; }

async function newSession() {
  const tpl = $('#template').value;
  const r = await api('/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ template_id: tpl }) });
  SESSION = r.session_id; LASTPROC = null; LASTNOTE = null; editing = false;
  $('#sessId').textContent = SESSION; setState(r.state); enableCapture(true);
  $('#empty').style.display = 'none'; $('#work').style.display = 'none';
  toast('Session started · ' + SESSION);
}

async function afterProcess(resp) {
  LASTPROC = resp; setState(resp.state); editing = false;
  $('#empty').style.display = 'none'; $('#work').style.display = 'block';
  await renderAll(); showTab('note');
  const segs = (LASTRAW && LASTRAW.segments || []).length;
  const pct = Math.round((resp.risk_score ?? 0) * 100);
  toast(`Draft ready — ${segs} transcript segment(s), risk ${pct}%. Review the note.`);
}
async function simulate() { busy(true); try { await afterProcess(await api(`/sessions/${SESSION}/simulate`, { method: 'POST' })); } catch (e) { toast(e.message, true); } busy(false); }
async function uploadFile() {
  const f = $('#file').files[0]; if (!f) { toast('choose an audio file', true); return; }
  busy(true);
  try { const fd = new FormData(); fd.append('file', f); await afterProcess(await api(`/sessions/${SESSION}/audio`, { method: 'POST', body: fd })); }
  catch (e) { toast('STT/processing failed: ' + e.message, true); }
  busy(false);
}
async function transition(state) {
  try {
    const r = await api(`/sessions/${SESSION}/state`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ state }) });
    setState(r.state); toast('→ ' + r.state.replace('_', ' '));
  } catch (e) { toast(e.message, true); }
}
function exportFmt(fmt) {
  fetch(API_BASE + `/sessions/${SESSION}/export/${fmt}`, { headers: headers() }).then(async r => {
    if (!r.ok) { const d = await r.json().catch(() => ({})); toast(d.detail || 'export failed', true); return; }
    const blob = await r.blob(); const url = URL.createObjectURL(blob); const a = document.createElement('a');
    const ext = fmt === 'markdown' ? 'md' : fmt; a.href = url; a.download = `${SESSION}.${ext}`; a.click(); URL.revokeObjectURL(url);
  });
}

// ---------- rendering ----------
async function renderAll() {
  const [note, risk, extr, raw, clean] = await Promise.all(
    ['note', 'risk', 'extraction', 'raw', 'clean'].map(k => api(`/sessions/${SESSION}/outputs/${k}`).catch(() => null)));
  LASTRAW = raw;
  renderNote(note); renderRisk(risk); renderExtraction(extr); renderTranscript(raw, clean); renderGrounding();
}
function renderNote(n) {
  LASTNOTE = n; const el = $('#tab-note');
  if (!n) { el.innerHTML = '<div class="card muted">No note.</div>'; return; }
  const editable = ['draft', 'in_review', 'edited'].includes(STATE);
  const secs = [...n.sections].sort((a, b) => a.order - b.order);
  const body = editing
    ? secs.map(s => `<div class="note-sec"><h4>${esc(s.label)}</h4>
        <textarea data-sec="${esc(s.section_id)}">${esc(s.content_text || '')}</textarea></div>`).join('')
    : secs.map(s => `<div class="note-sec"><h4>${esc(s.label)}</h4>
        <div class="body ${s.empty ? 'empty' : ''}">${s.empty ? 'Not discussed.' : esc(s.content_text)}</div></div>`).join('');
  const bar = !editable ? '' : (editing
    ? `<div class="editbar"><button class="btn sm" id="btnSaveEdit">Save changes</button>
         <button class="btn ghost sm" id="btnCancelEdit">Cancel</button>
         <span class="kv">Edits are saved to the note and mark it “edited”.</span></div>`
    : `<div class="editbar"><button class="btn ghost sm" id="btnEdit">✎ Edit note</button>
         <span class="kv">Refine the AI draft before approving.</span></div>`);
  el.innerHTML = `<div class="card">
    <div class="note-head"><h2>Consultation note</h2>
      <span class="badge state-${STATE}">${(STATE || '').replace('_', ' ')}</span>
      <span class="kv">${esc(n.template_id)}@${n.template_version}</span></div>
    ${bar}${body}</div>`;
  if (editable && !editing) $('#btnEdit').onclick = () => { editing = true; renderNote(LASTNOTE); };
  if (editable && editing) {
    $('#btnSaveEdit').onclick = saveEdits;
    $('#btnCancelEdit').onclick = () => { editing = false; renderNote(LASTNOTE); };
  }
}
async function saveEdits() {
  const sections = $$('#tab-note textarea').map(t => ({ section_id: t.dataset.sec, content_text: t.value }));
  try {
    const r = await api(`/sessions/${SESSION}/note`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sections }) });
    editing = false; setState(r.state); renderNote(r.note); toast('Note saved · ' + r.state.replace('_', ' '));
  } catch (e) { toast('save failed: ' + e.message, true); }
}
function renderRisk(r) {
  if (!r) { $('#tab-risk').innerHTML = '<div class="card muted">No risk assessment.</div>'; return; }
  const pct = Math.round((r.score || 0) * 100);
  const mk = (r.markers || []).map(m => `<div class="marker"><span class="sev ${m.severity}">${m.severity}</span>
    <div><b>${esc(m.type.replace(/_/g, ' '))}</b><div>${esc(m.message)}</div>
    <div class="kv">evidence: ${(m.evidence_span_ids || []).join(', ') || '—'} · non-authoritative</div></div></div>`).join('')
    || '<p class="muted">No risk markers.</p>';
  $('#tab-risk').innerHTML = `<div class="card"><h2 style="margin-top:0">Risk markers · attention score ${pct}%</h2>
    <div class="gauge"><div style="width:${pct}%"></div></div>${mk}
    <div class="disclaimer">${esc(r.disclaimer)}</div></div>`;
}
function renderExtraction(e) {
  if (!e) { $('#tab-extraction').innerHTML = '<div class="card muted">No extraction.</div>'; return; }
  const cc = (e.chief_complaints || []).map(c => `<li>${esc(c.symptom)}${c.duration ? ` <span class="kv">(${esc(c.duration)})</span>` : ''}${c.type ? ` <span class="kv">[${esc(c.type)}]</span>` : ''}</li>`).join('');
  const exByRegion = {}; (e.examination || []).forEach(f => { (exByRegion[f.region] = exByRegion[f.region] || []).push(`${f.finding}: ${esc(f.value)}`); });
  const ex = Object.entries(exByRegion).map(([r, v]) => `<li><b>${esc(r)}</b>: ${v.map(esc).join(', ')}</li>`).join('');
  const meds = (e.medications_discussed || []).map(m => `<li>${esc(m.name)} ${esc(m.dose || '')} ${esc(m.frequency || '')} <span class="sev moderate" style="font-size:9px">verify · non-authoritative</span></li>`).join('') || '<li class="muted">none discussed</li>';
  $('#tab-extraction').innerHTML = `<div class="card"><h2 style="margin-top:0">Clinical extraction (grounded)</h2>
    <p><b>Chief complaints</b></p><ul>${cc || '<li class="muted">none</li>'}</ul>
    <p><b>Examination</b></p><ul>${ex || '<li class="muted">none</li>'}</ul>
    <p><b>Medications discussed</b></p><ul>${meds}</ul>
    <details><summary class="muted">Raw extraction JSON</summary><pre>${esc(JSON.stringify(e, null, 2))}</pre></details></div>`;
}
function renderTranscript(raw, clean) {
  const lowset = new Set((clean && clean.low_confidence_span_ids) || []);
  const segs = (raw && raw.segments || []).map(s => {
    const low = lowset.has(s.id);
    return `<div class="seg"><span class="who ${s.speaker}">${s.speaker}</span>
      <div>${low ? `<span class="lowconf" title="low STT confidence">${esc(s.text)}</span>` : esc(s.text)}
      <div class="kv">${s.id} · ${s.language} · conf ${(s.confidence ?? 1).toFixed(2)}</div></div></div>`;
  }).join('') || '<p class="muted">No transcript.</p>';
  const corr = (clean && clean.corrections && clean.corrections.length) ? `<p class="kv">${clean.corrections.length} STT correction(s) applied; low-confidence spans highlighted.</p>` : '';
  $('#tab-transcript').innerHTML = `<div class="card"><h2 style="margin-top:0">Transcript (raw + clean overlay)</h2>${corr}${segs}</div>`;
}
function renderGrounding() {
  const g = LASTPROC && LASTPROC.grounding;
  if (!g) { $('#tab-grounding').innerHTML = '<div class="card muted">No grounding report.</div>'; return; }
  const list = a => a && a.length ? ('<ul>' + a.map(x => `<li>${esc(x)}</li>`).join('') + '</ul>') : '<p class="muted">none</p>';
  $('#tab-grounding').innerHTML = `<div class="card"><h2 style="margin-top:0">Grounding — “only what was said”</h2>
    <p>Kept <b>${g.kept}</b> grounded items · dropped <b>${(g.dropped || []).length}</b> · flagged <b>${(g.flagged || []).length}</b>.</p>
    <p><b>Dropped (ungrounded / not in transcript)</b></p>${list(g.dropped)}
    <p><b>Flagged</b></p>${list(g.flagged)}</div>`;
}
function showTab(t) {
  $$('.tabpane').forEach(p => p.style.display = 'none'); $('#tab-' + t).style.display = 'block';
  $$('.tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
}

// ---------- mic capture + listening visualizer ----------
let mediaStream = null, audioCtx = null, workletNode = null, scriptProc = null, analyser = null, freqData = null;
let chunks = [], recording = false, recStart = 0, recTimer = null, rafId = null;

function micSupported() { return !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia); }

function drawViz() {
  if (!recording) return;
  rafId = requestAnimationFrame(drawViz);
  const cv = $('#micCanvas'), ctx = cv.getContext('2d'); const w = cv.width, h = cv.height;
  ctx.clearRect(0, 0, w, h);
  if (!analyser) return;
  analyser.getByteFrequencyData(freqData);
  const accent = (getComputedStyle(document.documentElement).getPropertyValue('--accent') || '#0fb9a6').trim();
  ctx.fillStyle = accent;
  const bars = 40, step = Math.max(1, Math.floor(freqData.length / bars)), bw = w / bars;
  for (let i = 0; i < bars; i++) {
    const v = freqData[i * step] / 255;
    const bh = Math.max(2, v * h * 0.95);
    ctx.fillRect(i * bw + 1, (h - bh) / 2, bw - 2, bh);
  }
}

async function toggleRec() {
  if (recording) { stopRec(); return; }
  if (!micSupported()) {
    toast('Microphone needs https or localhost. Open the app at http://localhost:5173 (or :8000), or use Upload instead.', true);
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') await audioCtx.resume();
    const src = audioCtx.createMediaStreamSource(mediaStream);
    chunks = [];
    analyser = audioCtx.createAnalyser(); analyser.fftSize = 256; freqData = new Uint8Array(analyser.frequencyBinCount);
    src.connect(analyser);

    let captured = false;
    if (audioCtx.audioWorklet) {
      try {
        const code = "class P extends AudioWorkletProcessor{process(i){const c=i[0][0];if(c)this.port.postMessage(c.slice(0));return true;}}registerProcessor('pcm',P);";
        const url = URL.createObjectURL(new Blob([code], { type: 'application/javascript' }));
        await audioCtx.audioWorklet.addModule(url); URL.revokeObjectURL(url);
        workletNode = new AudioWorkletNode(audioCtx, 'pcm');
        workletNode.port.onmessage = e => chunks.push(new Float32Array(e.data));
        src.connect(workletNode); workletNode.connect(audioCtx.destination);
        captured = true;
      } catch (err) { console.warn('AudioWorklet unavailable, using ScriptProcessor:', err); }
    }
    if (!captured) {
      scriptProc = audioCtx.createScriptProcessor(4096, 1, 1);
      scriptProc.onaudioprocess = e => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      src.connect(scriptProc); scriptProc.connect(audioCtx.destination);
    }

    const cv = $('#micCanvas'); cv.width = cv.clientWidth || 280; cv.height = cv.clientHeight || 46;
    recording = true; recStart = Date.now();
    $('#micWrap').classList.add('live'); $('#micOrb').textContent = '🔴';
    $('#btnRec').textContent = '■ Stop & transcribe (0s)';
    $('#btnRec').classList.add('danger');
    recTimer = setInterval(() => {
      const s = Math.floor((Date.now() - recStart) / 1000);
      $('#btnRec').textContent = `■ Stop & transcribe (${s}s)`;
      $('#micStatus').innerHTML = `<b>Listening…</b> capturing the consultation — speak naturally, then press stop.`;
    }, 250);
    drawViz();
  } catch (e) { toast('mic unavailable: ' + e.message, true); cleanupRec(); }
}

function cleanupRec() {
  if (recTimer) { clearInterval(recTimer); recTimer = null; }
  if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
  workletNode && workletNode.disconnect(); scriptProc && scriptProc.disconnect(); analyser && analyser.disconnect();
  workletNode = scriptProc = analyser = null;
  mediaStream && mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null;
  $('#micWrap').classList.remove('live'); $('#micOrb').textContent = '🎙️';
  $('#btnRec').textContent = '● Record consultation'; $('#btnRec').classList.remove('danger');
  $('#micStatus').textContent = 'Ready — press record to start listening.';
  const cv = $('#micCanvas'); cv.getContext('2d').clearRect(0, 0, cv.width, cv.height);
}

async function stopRec() {
  recording = false;
  const sr = audioCtx ? audioCtx.sampleRate : 48000;
  const samples = flatten(chunks);
  cleanupRec();
  const wav = encodeWav(samples, sr, 16000);
  audioCtx && audioCtx.close(); audioCtx = null;
  if (samples.length === 0) { toast('No audio captured — check microphone permission/device, then try again.', true); return; }
  busy(true);
  try { const fd = new FormData(); fd.append('file', new Blob([wav], { type: 'audio/wav' }), 'consult.wav'); await afterProcess(await api(`/sessions/${SESSION}/audio`, { method: 'POST', body: fd })); }
  catch (e) { toast('STT/processing failed: ' + e.message, true); }
  busy(false);
}
function flatten(bufs) { let n = bufs.reduce((a, b) => a + b.length, 0); const o = new Float32Array(n); let i = 0; for (const b of bufs) { o.set(b, i); i += b.length; } return o; }
function encodeWav(samples, inRate, outRate) {
  const ratio = inRate / outRate, outLen = Math.floor(samples.length / ratio); const ds = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) ds[i] = samples[Math.floor(i * ratio)];
  const buf = new ArrayBuffer(44 + ds.length * 2); const v = new DataView(buf);
  const wr = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  wr(0, 'RIFF'); v.setUint32(4, 36 + ds.length * 2, true); wr(8, 'WAVE'); wr(12, 'fmt '); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, outRate, true); v.setUint32(28, outRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); wr(36, 'data'); v.setUint32(40, ds.length * 2, true);
  let o = 44; for (let i = 0; i < ds.length; i++) { const s = Math.max(-1, Math.min(1, ds[i])); v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true); o += 2; }
  return buf;
}

// ---------- finalize + signature ----------
let sigCtx = null, sigDrawing = false, sigHasInk = false, sigMode = 'draw', sigUploadData = null;

function buildPreview() {
  const n = LASTNOTE; const el = $('#signPreview');
  if (!n) { el.innerHTML = '<p class="muted">No note.</p>'; return; }
  el.innerHTML = `<div class="note-head"><h2 style="font-size:16px;margin:0">Consultation note</h2>
      <span class="kv">${esc(n.template_id)}@${n.template_version}</span></div>`
    + [...n.sections].sort((a, b) => a.order - b.order).map(s => `<div class="note-sec"><h4>${esc(s.label)}</h4>
        <div class="body ${s.empty ? 'empty' : ''}">${s.empty ? 'Not discussed.' : esc(s.content_text)}</div></div>`).join('');
}
function initSigPad() {
  const cv = $('#sigPad'); cv.width = cv.clientWidth || 320; cv.height = 150;
  sigCtx = cv.getContext('2d');
  sigCtx.lineWidth = 2.3; sigCtx.lineCap = 'round'; sigCtx.lineJoin = 'round'; sigCtx.strokeStyle = '#15302b';
  sigHasInk = false;
  const pos = e => { const r = cv.getBoundingClientRect(); const t = e.touches ? e.touches[0] : e; return [t.clientX - r.left, t.clientY - r.top]; };
  cv.onmousedown = cv.ontouchstart = e => { e.preventDefault(); sigDrawing = true; const [x, y] = pos(e); sigCtx.beginPath(); sigCtx.moveTo(x, y); };
  cv.onmousemove = cv.ontouchmove = e => { if (!sigDrawing) return; e.preventDefault(); const [x, y] = pos(e); sigCtx.lineTo(x, y); sigCtx.stroke(); sigHasInk = true; };
  cv.onmouseup = cv.onmouseleave = cv.ontouchend = () => { sigDrawing = false; };
}
function clearSig() { if (sigCtx) sigCtx.clearRect(0, 0, $('#sigPad').width, $('#sigPad').height); sigHasInk = false; }
function setSigMode(mode) {
  sigMode = mode;
  $('#sigTabDraw').classList.toggle('active', mode === 'draw');
  $('#sigTabUpload').classList.toggle('active', mode === 'upload');
  $('#sigDrawPane').style.display = mode === 'draw' ? 'block' : 'none';
  $('#sigUploadPane').style.display = mode === 'upload' ? 'block' : 'none';
}
function openSign() {
  if (!LASTNOTE) { toast('no note to finalize yet', true); return; }
  $('#sigName').value = ''; sigUploadData = null;
  $('#sigUploadPreview').style.display = 'none'; $('#sigFile').value = '';
  setSigMode('draw');
  $('#signModal').style.display = 'flex';
  initSigPad(); buildPreview();
}
function closeSign() { $('#signModal').style.display = 'none'; }
async function confirmFinalize() {
  const name = $('#sigName').value.trim();
  if (!name) { toast('enter the signing clinician name', true); $('#sigName').focus(); return; }
  let img = null;
  if (sigMode === 'draw' && sigHasInk) img = $('#sigPad').toDataURL('image/png');
  else if (sigMode === 'upload' && sigUploadData) img = sigUploadData;
  try {
    const r = await api(`/sessions/${SESSION}/state`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state: 'finalized', signed_by_name: name, signature_image: img })
    });
    setState(r.state); closeSign(); toast('Finalized & signed by ' + name);
    await renderAll(); showTab('note');
  } catch (e) { toast('finalize failed: ' + e.message, true); }
}

// ---------- template builder ----------
let BLOCKS = [], blkSeq = 0;
function slug(s) { return (s || '').toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, ''); }
async function openBuilder() {
  $('#builder').style.display = 'flex';
  if (!$('#bPalette').dataset.loaded) {
    try {
      const comps = await api('/templates/components');
      $('#bPalette').insertAdjacentHTML('beforeend', comps.map(c =>
        `<div class="pal-item" draggable="true" data-comp="${esc(c.component)}">${esc(c.label)}</div>`).join(''));
      $$('#bPalette .pal-item').forEach(el => el.addEventListener('dragstart', ev => ev.dataTransfer.setData('text/component', el.dataset.comp)));
      $('#bPalette').dataset.loaded = '1';
    } catch (e) { toast('palette failed: ' + e.message, true); }
  }
}
function closeBuilder() { $('#builder').style.display = 'none'; }
function addBlock(component) {
  const label = component.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  BLOCKS.push({ uid: 'b' + (++blkSeq), component, label, enabled: true, schema_hint: '' });
  renderBlocks();
}
function renderBlocks() {
  const drop = $('#bDrop');
  if (!BLOCKS.length) { drop.className = 'drop empty'; drop.innerHTML = 'Drag components here'; return; }
  drop.className = 'drop';
  drop.innerHTML = BLOCKS.map(b => `
    <div class="blk" draggable="true" data-uid="${b.uid}">
      <div class="blk-top">
        <span class="comp">${esc(b.component)}</span>
        <input type="text" value="${esc(b.label)}" data-f="label" title="section label"/>
        <label class="kv"><input type="checkbox" data-f="enabled" ${b.enabled ? 'checked' : ''}/> on</label>
        <button class="x" data-f="remove" title="remove">✕</button>
      </div>
      ${b.component === 'CUSTOM' ? `<div class="hintrow"><input type="text" placeholder="schema_hint e.g. examination.nose" value="${esc(b.schema_hint)}" data-f="hint"/></div>` : ''}
    </div>`).join('');
  $$('#bDrop .blk').forEach(el => {
    const b = BLOCKS.find(x => x.uid === el.dataset.uid);
    el.querySelector('[data-f=label]').addEventListener('input', e => b.label = e.target.value);
    el.querySelector('[data-f=enabled]').addEventListener('change', e => b.enabled = e.target.checked);
    const hint = el.querySelector('[data-f=hint]'); if (hint) hint.addEventListener('input', e => b.schema_hint = e.target.value);
    el.querySelector('[data-f=remove]').addEventListener('click', () => { BLOCKS = BLOCKS.filter(x => x.uid !== b.uid); renderBlocks(); });
    el.addEventListener('dragstart', ev => { ev.dataTransfer.setData('text/reorder', b.uid); el.classList.add('dragging'); });
    el.addEventListener('dragend', () => el.classList.remove('dragging'));
  });
}
function reorderTo(uid, y) {
  const moving = BLOCKS.find(b => b.uid === uid); if (!moving) return;
  const els = [...$$('#bDrop .blk')]; let idx = BLOCKS.length;
  for (let i = 0; i < els.length; i++) { const r = els[i].getBoundingClientRect(); if (y < r.top + r.height / 2) { idx = i; break; } }
  const cur = BLOCKS.findIndex(b => b.uid === uid);
  BLOCKS.splice(cur, 1); if (cur < idx) idx--; BLOCKS.splice(idx, 0, moving);
  renderBlocks();
}
function setupBuilderDnd() {
  const drop = $('#bDrop');
  drop.addEventListener('dragover', ev => { ev.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', ev => {
    ev.preventDefault(); drop.classList.remove('over');
    const comp = ev.dataTransfer.getData('text/component');
    const reUid = ev.dataTransfer.getData('text/reorder');
    if (comp) addBlock(comp); else if (reUid) reorderTo(reUid, ev.clientY);
  });
}
async function saveTemplate() {
  const name = $('#bName').value.trim();
  if (!name) { toast('enter a template name', true); return; }
  if (!BLOCKS.length) { toast('add at least one component', true); return; }
  let body;
  try {
    const used = {};
    const sections = BLOCKS.map((b, i) => {
      let base = slug(b.label) || ('sec' + (i + 1)), id = base, n = 1;
      while (used[id]) id = base + '_' + (++n); used[id] = 1;
      const s = { id, component: b.component, label: b.label.trim() || b.component, enabled: b.enabled, order: i + 1 };
      if (b.component === 'CUSTOM') {
        if (!b.schema_hint.trim()) throw new Error('CUSTOM block "' + b.label + '" needs a schema_hint');
        s.schema_hint = b.schema_hint.trim();
      }
      return s;
    });
    const tid = slug($('#bId').value) || slug(name) || 'tpl';
    body = { template_id: tid, name, sections };
    const hosp = $('#bHosp').value.trim(); if (hosp) body.hospital_id = hosp;
  } catch (e) { toast(e.message, true); return; }
  try {
    const r = await api('/templates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    toast('Saved template ' + r.template_id + '@' + r.version);
    await loadTemplates(); $('#template').value = r.template_id;
    closeBuilder();
  } catch (e) { toast('save failed: ' + e.message + (/403/.test(e.message) ? ' (use the doctor or admin role)' : ''), true); }
}

// ---------- wire up ----------
$('#btnNew').onclick = newSession;
$('#btnSim').onclick = simulate;
$('#btnUpload').onclick = uploadFile;
$('#btnRec').onclick = toggleRec;
$('#btnBuilder').onclick = openBuilder;
$('#bClose').onclick = closeBuilder;
$('#bSave').onclick = saveTemplate;
$('#btnFinalize').onclick = openSign;
$('#sClose').onclick = closeSign;
$('#sConfirm').onclick = confirmFinalize;
$('#sigClear').onclick = clearSig;
$('#sigTabDraw').onclick = () => setSigMode('draw');
$('#sigTabUpload').onclick = () => setSigMode('upload');
$('#sigFile').onchange = e => {
  const f = e.target.files[0]; if (!f) return;
  const rd = new FileReader();
  rd.onload = () => { sigUploadData = rd.result; const img = $('#sigUploadPreview'); img.src = rd.result; img.style.display = 'block'; };
  rd.readAsDataURL(f);
};
setupBuilderDnd();
$$('[data-state]').forEach(b => b.onclick = () => transition(b.dataset.state));
$$('.ex').forEach(b => b.onclick = () => exportFmt(b.dataset.fmt));
$$('.tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
loadHealth(); loadTemplates();
