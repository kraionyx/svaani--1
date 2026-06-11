# Karaionyx — AI Medical Scribe

A production-oriented **AI medical scribe**: it listens to a doctor–patient
consultation, transcribes it (Sarvam V3 `saaras:v3` — multilingual; doctor/patient
diarization via the Batch API), and turns the
conversation into a **template-driven consultation note** plus a structured,
auditable record — for **doctor review and sign-off**.

> **Founding principle — faithful scribe, not clinical decision-maker.**
> The AI transcribes, cleans, and *structures only what was actually said*. It never
> invents symptoms, never suggests treatments, and **never authors prescriptions**.
> Its one value-add beyond faithful structuring is a *non-authoritative* risk-marker
> layer that flags risk indications already present in the conversation for the
> doctor's attention.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and
[`docs/llm-comparison.md`](docs/llm-comparison.md) for the LLM selection.

## Outputs

1. **Raw transcript** — verbatim Sarvam V3; speaker-labeled when produced via the Batch API.
2. **Clean transcript** — obvious STT fixes, meaning preserved, low-confidence flags.
3. **Clinical extraction JSON** — only entities *mentioned*, each with provenance.
4. **Consultation note** — rendered against the selected hospital template.
5. **Risk markers / score** — non-authoritative preview warnings, with evidence spans.

(There is no AI-generated prescription. Medicines *discussed* are captured verbatim
under `medications_discussed`, marked `authoritative=false`.)

## Run

```bash
python -m venv venv && venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
# → GET http://127.0.0.1:8000/health
#   POST /sessions {"template_id":"ent"} then POST /sessions/{id}/simulate
```

Runs with **no credentials**: Sarvam/Vertex calls fall back to deterministic mocks
and PHI redaction degrades to a regex redactor.

## Configure (env, prefix `SCRIBE_`)

| Variable | Purpose |
|---|---|
| `SCRIBE_SARVAM_API_KEY` | Sarvam V3 STT; diarization via Batch API (mock if unset) |
| `SCRIBE_VERTEX_API_KEY` | Vertex express-mode API key — enables Gemini (disabled if unset) |
| `SCRIBE_VERTEX_PROJECT` | Alternative to the key: project (+`SCRIBE_VERTEX_LOCATION`) for regional residency |
| `SCRIBE_VERTEX_LOCATION` | default `asia-south1` (Mumbai — India PHI residency) |
| `SCRIBE_GEMINI_MODEL` | default `gemini-2.5-pro` |
| `SCRIBE_PHI_ENCRYPTION_KEY_B64` | base64 32-byte AES-GCM key (`python -c "from app.security.crypto import generate_key_b64 as g; print(g())"`) |
| `SCRIBE_DROP_UNGROUNDED_FIELDS` | `true` (drop) / `false` (flag) ungrounded items |

Install the optional integrations (`google-genai`, `presidio-analyzer`) from the
commented section of `requirements.txt` for live behaviour.

## Test

```bash
pytest
```

Covers schema invariants, the ENT template render round-trip (the brief's example),
grounding ("ungrounded item is dropped"), risk markers, and the no-prescription
contract.

## Layout

```
app/
  schemas/     transcript · clinical · risk · template · note · session
  audio/       WebSocket ingest
  stt/         Sarvam V3 client (+ mock)
  llm/         MedicalLLM protocol + Gemini-on-Vertex
  pipeline/    clean → extract → note → risk → orchestrator
  templates/   registry + renderer
  validation/  grounding + confidence
  security/    rbac · audit · crypto · redact
  export/      exporter + pdf
docs/          ARCHITECTURE.md · llm-comparison.md · templates/*.json
tests/
```
