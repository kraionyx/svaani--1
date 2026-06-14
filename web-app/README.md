# Svaani web-app (Vite + React + TypeScript)

The real-time streaming frontend. Live transcript while recording, a note that streams
in token-by-token, real-time risk markers, structured editors for the note / extraction /
risk, and digital sign-off.

## Develop
```bash
npm install
npm run dev          # http://localhost:5173 (talks to the API on :8000)
```
Run the backend in another terminal: `uvicorn app.main:app --reload` (project root).

## Build
```bash
npm run build        # type-checks (tsc) then bundles to web-app/dist
```
The FastAPI app serves `web-app/dist` at **`/app`** (and `/` redirects there once built).

## How it talks to the backend
- **Streaming consult:** WebSocket `…/ws/consultation` — sends 16 kHz PCM frames, receives
  `final_segment`, `note_chunk`, `risk_warning`, `draft_ready` events (`src/ws.ts`, `src/audio.ts`).
- **REST:** sessions, outputs, structured edits, export — `src/api.ts`. API/WS base URLs are
  auto-detected (same-origin when served at `/app`, else `http://127.0.0.1:8000`).
