# Intelligent Scribe Redesign — Design & Plan

> **Status: backend implemented (all 13 goals + prescription preview); React UI deferred.**
> Each goal maps to the real code seam below; additions are feature-flagged and the founding
> safety contract (faithful scribe, grounding gate, no AI-authored prescriptions, human
> sign-off) is intact. Full suite: **47 passed, 1 skipped**.

## Implementation status (backend)

| Goal | Status | Where |
|---|---|---|
| 1 Relationship/subject resolution | ✅ | [pipeline/subjects.py](../../app/pipeline/subjects.py), prompt `RELATIONSHIP_INSTRUCTION`, `ClinicalExtraction.referenced_patient` |
| 2 Complexity detection | ✅ | [pipeline/complexity.py](../../app/pipeline/complexity.py) |
| 3 Real-time/Batch + Auto | ✅ | [pipeline/inference_mode.py](../../app/pipeline/inference_mode.py), `SCRIBE_AUTO_INFERENCE_MODE` |
| 4 Confidence indicator | ✅ | `ConversationProfile.confidence_band`, `GET /sessions/{id}/profile` |
| 5 Notice bar | ✅ (event) | WS `mode_switch` + `confidence_update` in [audio/ws.py](../../app/audio/ws.py) |
| 6 Speaker timeline + correction | ✅ | `PATCH /sessions/{id}/speakers` → re-render |
| 7 Consultation review | ✅ | `POST /sessions/{id}/review` |
| 8 Admin console | ✅ | `GET /admin/reviews`, `PATCH /admin/reviews/{id}` (admin/auditor RBAC) |
| 9 Improvement pipeline | ✅ | `GET /admin/improvements`, `POST …/advance` (human-gated) |
| 10 Prompt/model versioning | ✅ | `GET/POST /prompts`, `POST /prompts/{id}/activate`, `GET /models` |
| 11 AI consultation editor | ✅ | `POST /sessions/{id}/ai-edit` (preview) + `/ai-edit/apply` + `/edits` |
| 12 Performance | ✅ | classifier/confidence are in-loop & deterministic; heavy work stays `to_thread` |
| 13 Best practices | ✅ | `feature_flags`, telemetry table, RBAC, audit, versioning |
| Prescription preview | ✅ | [templates/document_renderer.py](../../app/templates/document_renderer.py), `POST /sessions/{id}/document/preview`, `PUT /documents/{id}`, `/approve` |

Ops/quality data lives in the in-memory [data/repo.py](../../app/data/repo.py) (same surface as the
Supabase tables in `supabase/schema.sql`; swap in when `SCRIBE_STORE_BACKEND=supabase`). The
React UI for these endpoints is the remaining follow-up.

---


---

## 0. Guiding constraints (do not break)

- **Faithful scribe.** Structure only what was said. Grounding gate
  ([validation/grounding.py](../../app/validation/grounding.py)) + fidelity
  ([validation/fidelity.py](../../app/validation/fidelity.py)) stay authoritative.
- **No AI-authored prescriptions.** `MedicationMention.authoritative` stays validator-forced
  `False` ([schemas/clinical.py](../../app/schemas/clinical.py)). The prescription *preview*
  is a hospital-branded **formatting + sign-off** layer over doctor-confirmed content — not
  AI clinical decision-making.
- **Only FINALIZED is exportable** ([schemas/session.py](../../app/schemas/session.py)).
- **Everything is feature-flagged** through [config.py](../../app/config.py) and degrades to
  the current behaviour when off / when no LLM/STT key is present.

---

## Goal 1 — Intelligent conversation understanding (relationship resolution)

**Root cause in current code:** [stt/sarvam.py `_role_for()`](../../app/stt/sarvam.py#L34-L47)
assigns *first speaker → DOCTOR, second → PATIENT*. There is no caregiver concept and the
extraction never resolves *who the symptoms are about*. So "Mother speaks for Son" →
`Patient = Mother`.

**Design:**
1. **Extend `SpeakerRole`** (additive enum values: `CAREGIVER`, `NURSE`, `TRANSLATOR`) and add
   a new **`RelationshipResolution`** schema: `{speaker_label, role, relationship(self/parent/
   spouse/guardian/translator/...), subject_patient}`.
2. **New pipeline stage `resolve_subjects`** (runs after `clean`, before/with `extract`). A
   small Gemini call (or rule pass when no LLM) reads diarized turns + cue phrases
   ("my son", "I'm speaking for my father", "she has…") and emits the relationship map +
   the **referenced patient**. Grounded like everything else (cites span ids).
3. **Extraction prompt update** ([pipeline/prompts.py](../../app/pipeline/prompts.py)): add a
   hard rule — *"The patient is the person the complaints are ABOUT, not necessarily the
   speaker. Attribute symptoms/history to `referenced_patient`."*
4. Persist to `consultations.referenced_patient` + `speaker_segments` (see schema §6).

**Never assume current speaker = patient** is enforced by making subject resolution an
explicit, grounded step rather than an STT-order heuristic.

---

## Goal 2 — Conversation complexity detection

**Lightweight classifier** (`app/pipeline/complexity.py`, new), pure-Python + optional LLM
signal, returns `complexity_score ∈ [0,1]` from:

| Signal | Source |
|---|---|
| unique speaker count | diarization (`speaker_segments`) |
| relationship ambiguity | Goal-1 resolver confidence |
| interruptions / cross-talk | overlapping `start_ms`/`end_ms` spans |
| pronoun ambiguity | cheap regex/heuristic on clean text |
| multiple referenced patients | Goal-1 output |
| background speech / poor audio | mean ASR `confidence` (already on `TranscriptSegment`) |
| diarization confidence | Sarvam batch metadata |

If `score > SCRIBE_COMPLEXITY_THRESHOLD` (config flag, default e.g. 0.6) ⇒ `is_complex=true`.
Runs on the **live transcript during the consult** (cheap, no extra round-trip), updating
continuously — feeds Goals 3 & 4.

---

## Goal 3 — Real-time vs Batch + Auto mode

Builds directly on the **existing hybrid finalize** ([audio/ws.py `_finalize`](../../app/audio/ws.py#L313-L353))
which already does *fast live draft → batch-diarized refine*.

- **Manual mode:** doctor picks Real-time or Batch (UI toggle → `inference_mode` on session).
- **Auto mode (`SCRIBE_AUTO_INFERENCE_MODE`):** the complexity classifier (Goal 2) monitors
  during capture. Simple ⇒ stay realtime (current streaming path). Crosses threshold ⇒ flip
  to batch: keep buffering, suppress the fast-pass draft, wait for the diarized pass, and emit
  the notice banner (Goal 5). The seam already exists — `hybrid_refine` + `_diarize()`; Auto
  mode just *chooses* which pass the doctor sees as authoritative.
- Transition is seamless because both paths already run; Auto only changes which result is
  surfaced first.

---

## Goal 4 — Accuracy / confidence indicator

`confidence_band` (`high≥0.9 / moderate≥0.75 / low`) derived from `audio_confidence`
(diarization+ASR) blended with `complexity_score`. Reasons list = the firing signals from
Goal 2 (multiple speakers, relationship ambiguity, background noise, cross-talk, poor audio).
Emitted over WS as a new `confidence_update` event and rendered as the 🟢/🟡/🔴 chip. Already
have per-segment `confidence` and `low_confidence_span_ids` to source this.

---

## Goal 5 — Intelligent notice bar

New WS event `mode_switch` `{from, to, reason, est_delay_s}` emitted by Auto mode (Goal 3).
Frontend shows a transient banner ("Multiple speakers detected. Switching to Batch
Processing… ~3–5 s") that auto-dismisses. Pure additive UI + one event type.

---

## Goal 6 — Speaker timeline + correction

- **Data:** `speaker_segments` table (schema §6) — role, relationship, subject, confidence,
  encrypted text, plus `corrected_role/corrected_by/corrected_at`.
- **API:** `PATCH /sessions/{id}/speakers` (new) → updates roles/subjects, then calls the
  existing `rebuild_from_extraction` ([orchestrator.py](../../app/pipeline/orchestrator.py#L106-L131))
  so a correction **immediately re-renders the note** (deterministic, no LLM). This reuses the
  exact mechanism the structured editors already use.
- **UI:** a Timeline tab (sibling of the existing Tabs) listing turns with a role dropdown.

---

## Goal 7 — Consultation review (doctor feedback)

- **End-of-consult prompt:** 👍 Helpful / 👎 Needs Improvement.
- 👎 opens structured categories = the `error_category` enum (wrong patient, wrong speaker,
  SOAP error, medication error, timeline, prompt misunderstanding, missing diagnosis,
  hallucination, other) + free text.
- **API:** `POST /sessions/{id}/review` → `consultation_reviews` table. Captures the context
  snapshot (model/prompt version, inference mode, audio confidence, speaker count) so the
  admin console has everything without re-deriving.

---

## Goal 8 — Admin review console

- Trigger `enqueue_admin_review` (in SQL) auto-pushes every `needs_improvement` review into
  `admin_reviews` with status `pending`.
- **Admin dashboard** (new route in the SPA + admin-only API): filter/search by
  `error_category`, status (pending/approved/rejected/resolved), model/prompt version. RBAC:
  `admin`/`auditor` only (RLS enforced, see schema §16).

---

## Goal 9 — Continuous improvement pipeline (never auto-deploys prompts)

`improvement_items` table models the staged flow:
`issue_classification → prompt_evaluation → regression_test_generation → prompt_optimization
→ offline_validation → human_approval → deployed`. Approved admin reviews seed an item; a
candidate prompt + generated regression test live **offline only**. Production prompts change
*only* by promoting a `prompt_versions` row via human approval — never written from the live
path.

---

## Goal 10 — Prompt & model versioning

`prompt_versions` (name, version, content, `content_hash`, active) and `model_versions`
(provider, model_id). Each consultation records `model_version` + `prompt_version` for
rollback/audit. The pipeline reads the **active** prompt row instead of the hardcoded strings
in [pipeline/prompts.py](../../app/pipeline/prompts.py) (those become the seed v1).

---

## Goal 11 — AI consultation editor (natural-language edits)

- Toggle in the edit page. Doctor types "Move diabetes into past medical history", etc.
- **API:** `POST /sessions/{id}/ai-edit` → Gemini receives the current section(s) + instruction
  under a strict system prompt ("modify ONLY the requested section; preserve all else; you may
  not invent clinical content"). Returns a **diff/preview**; nothing applies until the doctor
  approves.
- **History / undo-redo:** `consultation_edits` table (seq, before_enc, after_enc, applied,
  undone). Apply re-renders via the existing note/extraction edit endpoints so grounding +
  fidelity re-run.

---

## Goal 12 — Performance

- Complexity classifier and confidence are **cheap, in-loop** (no extra LLM round-trip for
  simple cases) — simple consults stay on the current single-pass Flash path
  ([pipeline/combined.py](../../app/pipeline/combined.py)).
- Heavy work (batch diarization, AI editor, ICD/coding) stays **async / off the event loop**
  via `asyncio.to_thread` (already the pattern in [main.py](../../app/main.py) and
  [audio/ws.py](../../app/audio/ws.py)).
- Relationship resolution folds into the existing combined call where possible (one schema
  field), avoiding a new round-trip.

---

## Goal 13 — Engineering best practices

Most already exist; the redesign extends them:

| Practice | Existing | Add |
|---|---|---|
| Feature flags | [config.py](../../app/config.py) `SCRIBE_*` | `feature_flags` table for per-hospital runtime flags |
| Observability | [observability.py](../../app/observability.py) Prometheus `/metrics` | `stage_latencies` table for per-stage timing |
| Prompt/model versioning | hardcoded prompts | `prompt_versions`/`model_versions` |
| Audit logs | [security/audit.py](../../app/security/audit.py) JSONL | `audit_events` hash-chained in Postgres |
| Fallback logic | staged-pipeline fallback, batch→live fallback | unchanged |
| RBAC | [security/rbac.py](../../app/security/rbac.py) | RLS in Supabase (defense in depth) |
| Secure PHI | AES-GCM [crypto.py](../../app/security/crypto.py) | encrypted blobs in Supabase (`*_enc`) |
| Regression / A-B | pytest grounding/no-Rx gates | prompt A/B via `prompt_versions.active` + improvement pipeline |

---

## Prescription / hospital-document preview (your new feature)

**Reconciliation:** the AI does **not** author the prescription. The doctor's confirmed note +
discussed medications are injected into the **hospital's own HTML design** for a printable
document the doctor edits and signs.

**Mechanism:**
1. You provide the hospital design as **HTML/CSS with `{{placeholders}}`** (logo, hospital
   name, address, regn no, doctor name/reg, patient block, Rx lines, signature, footer).
2. Stored in `document_templates` (versioned, per hospital, schema §4).
3. **Renderer** (`app/templates/document_renderer.py`, new — analogous to the deterministic
   [renderer.py](../../app/templates/renderer.py)) fills placeholders from the finalized
   note/extraction + hospital branding. Pure, deterministic, no new clinical content.
4. **Preview → edit → approve:** rendered into `rendered_documents` (`draft → previewed →
   edited → approved → signed`). Doctor edits the HTML, approves, then it joins the existing
   sign-off + PDF export ([export/pdf.py](../../app/export/pdf.py)).
5. **API:** `GET /sessions/{id}/document/{doc_type}/preview`, `PUT …/document/{id}`,
   `POST …/document/{id}/approve`. Gated on doctor RBAC + FINALIZED for export.

When you send the HTML design, it drops straight into `document_templates.html` with a
documented placeholder list.

---

## Supabase integration (do not change existing store; add a backend)

- New `app/store_supabase.py` implementing the same `SessionStore` interface as
  [store_sql.py](../../app/store_sql.py), selected by `SCRIBE_STORE_BACKEND=supabase`. It writes
  PHI to `consultations.session_enc/result_enc` (AES-GCM via existing `FieldCipher`) and
  metadata to the plain columns. `get_store()` already dispatches on the backend flag.
- Connection: Supabase **pooler (pgbouncer)** URI, not direct (the `t4g.nano` caps ~60 conns).
- Secrets via env only (`SCRIBE_SUPABASE_URL`, `SCRIBE_SUPABASE_SERVICE_KEY`, DB URL).
- **service_role key is server-side only**; browsers use anon key + RLS.

### Event flow (additions, dashed = new)
```
mic → WS → STT(stream) → live segments → complexity(loop) ──▶ confidence_update
                                              │ if Auto & complex ─▶ mode_switch (notice)
 stop → diarize(batch) → resolve_subjects(NEW) → clean → extract → ground → note → risk
        → consultations + speaker_segments(NEW) → draft_ready
 doctor: review(👍/👎)→consultation_reviews→[needs_improvement]→admin_reviews→improvement_items
 doctor: AI edit → preview → approve → consultation_edits ; speaker fix → re-render
 finalize → rendered_documents (hospital template) → PDF export
```

---

## Risks & mitigations (delta)

| Risk | Mitigation |
|---|---|
| PHI in Singapore region vs India residency posture | All clinical PHI stored encrypted (keys outside Supabase); explicit residency decision required before real PHI |
| Relationship resolver wrong | Grounded + low-confidence flagged; doctor speaker-timeline correction re-renders note |
| Auto mode flips distractingly | Hysteresis + single transient banner; manual override always available |
| Prescription preview perceived as AI-prescribing | Doctor-confirmed content only, explicit approve+sign, no AI Rx authoring |
| Connection exhaustion on nano DB | pgbouncer pooler, short-lived connections |
| Leaked anon/db credentials | Rotate DB password; service_role server-side only; RLS on every table |

---

## What this plan does NOT do yet (your decisions)

1. Confirm the prescription-preview reconciliation above (formatting layer, not AI Rx).
2. Confirm PHI may reside in Singapore, or require an India region / keep PHI India-only.
3. Whether to wire Supabase now or keep `sqlite` and add Supabase later.
4. Send the hospital HTML design to seed `document_templates`.
