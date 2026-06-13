# Run Svaani — AI Medical Scribe

Commands to set up and run the application. **Windows / PowerShell** is the primary
path (your environment); a bash equivalent is given where it differs.

> The app now runs as **two processes on separate ports**: the FastAPI **backend on
> `:8000`** (API + WebSocket) and the static **frontend on `:5173`** (`web/`). CORS is
> pre-configured to allow the `:5173` origin.

> Run everything from the **`svaani--1`** directory — that's where the `app/` package,
> `web/` frontend, `requirements.txt`, and `pyproject.toml` live, and where the server
> resolves `.env`.

```powershell
cd c:\Users\salve\OneDrive\Desktop\kraionyx_version001\svaani--1
```

---

## 1. Prerequisites

- **Python 3.11+** (you have 3.12.10 — `python --version`).

---

## 2. One-time setup (virtual env + dependencies)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- If activation is blocked by execution policy, run once in this shell:
  `Set-ExecutionPolicy -Scope Process -Bypass`, then re-run the activate line.
- **cmd.exe** instead of PowerShell: `.\.venv\Scripts\activate.bat`
- **bash / Git Bash:** `python -m venv .venv && source .venv/Scripts/activate`

`requirements.txt` already includes `google-genai` (Gemini/Vertex) and `sarvamai`
(Sarvam V3), so installing it enables **live** providers.

---

## 3. Enable live Sarvam + Gemini (`.env` placement)

Your real keys are in the **repo-root** `.env`
(`...\kraionyx_version001\.env`, model = `gemini-2.5-flash`), but settings are read
relative to the run directory. Copy it into `svaani--1\` so the server picks it up:

```powershell
Copy-Item ..\.env .\.env
```

- Skip this step to run **keyless**: Sarvam/Vertex calls fall back to deterministic
  mocks and PHI redaction degrades to regex — the app and the UI still work end-to-end.
- `.env` is gitignored; don't commit it.

---

## 4. Run the backend (API, port 8000)

```powershell
uvicorn app.main:app --reload
```

- Serves the API + WebSocket on **http://127.0.0.1:8000**.
- Expose on your LAN: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Stop the server: **Ctrl+C**.

## 4b. Run the frontend (UI, port 5173) — separate terminal

```powershell
python -m http.server 5173 -d web
```

- Open the dashboard at **http://localhost:5173/**. It calls the backend on `:8000`
  (auto-detected; override origins with `SCRIBE_CORS_ALLOW_ORIGINS` on the backend).
- The microphone needs a secure context — `localhost` qualifies, so mic capture works.
- bash is identical. To change the allowed origins:
  `$env:SCRIBE_CORS_ALLOW_ORIGINS="http://localhost:5173"` before starting uvicorn.

> Prefer a single process? The backend also serves the same `web/` UI at
> **http://127.0.0.1:8000/** — open that and skip step 4b (no CORS needed).

---

## 5. Verify it's up

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expect `status = ok`. `sarvam`/`vertex` read `live` when `.env` keys are present,
`mock`/`disabled` otherwise.

Open the dashboard: **http://localhost:5173/** (two-process) or **http://127.0.0.1:8000/**
(single-process). Pick a theme (Mint / White / Dark) from the top-right switch; edit
the generated note in the **Consultation note** tab; finalize with a drawn or uploaded
**digital signature**.

---

## 6. Smoke test the pipeline (no audio needed)

Runs the canned ENT consultation through clean → extract → ground → note → risk:

```powershell
$base = "http://127.0.0.1:8000"
$s = Invoke-RestMethod -Method Post "$base/sessions" -ContentType application/json -Body '{"template_id":"ent"}'
Invoke-RestMethod -Method Post "$base/sessions/$($s.session_id)/simulate"
```

Returns the rendered `note_markdown`, `risk_score`, and `grounding` report.

**Transcribe a real recording** (uses live Sarvam if configured):

```powershell
$s = Invoke-RestMethod -Method Post "$base/sessions" -ContentType application/json -Body '{"template_id":"soap"}'
Invoke-RestMethod -Method Post "$base/sessions/$($s.session_id)/audio" -Form @{ file = Get-Item .\consult.wav }
```

> Live audio: a doctor↔patient WAV captured from the browser mic streams over the
> WebSocket `/ws/consultation` (binary frames + `start`/`stop` control); the dashboard
> at `/ui/` drives this for you.

---

## 7. Run the tests

```powershell
pytest
```

21 tests — schema invariants, ENT template render, grounding, risk markers, and the
no-prescription contract. Hermetic (forces mock STT + disabled LLM), so they pass
with or without keys.

---

## Quick reference

| Action | Command |
|---|---|
| Activate venv | `.\.venv\Scripts\Activate.ps1` |
| Start backend (:8000) | `uvicorn app.main:app --reload` |
| Start frontend (:5173) | `python -m http.server 5173 -d web` |
| Health check | `Invoke-RestMethod http://127.0.0.1:8000/health` |
| Dashboard | open `http://localhost:5173/` (or `http://127.0.0.1:8000/`) |
| Smoke test | `POST /sessions` → `POST /sessions/{id}/simulate` |
| Tests | `pytest` |
| Stop server | `Ctrl+C` |
