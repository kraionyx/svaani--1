# 5. API Design

Covers deliverable **#7**. The API already exists in `app/main.py`; this catalogs it, marks what the
redesign **adds/changes**, and states conventions. Base URL: backend on `:8000`. Auth headers today:
`X-User-Id`, `X-Role` (dev mode); JWT bearer in `jwt` mode (`app/security/auth.py`).

## 5.1 Conventions

- **Auth & RBAC:** every PHI/admin route is guarded by `require_permission` (`app/security/rbac.py`).
  Roles: `doctor`, `scribe`, `admin`, `auditor`.
- **Audit:** every PHI-touching call writes an `audit_events` row (hash-chained).
- **Errors:** JSON `{detail: "..."}` with standard HTTP codes; LLM/STT failures degrade to
  deterministic output rather than 5xx where possible.
- **Idempotency:** session-scoped writes are upserts keyed by `session_id`.
- **Versions:** responses for notes/reviews carry `model_version` + `prompt_version`.

## 5.2 Existing endpoints (keep)

### Sessions & clinical
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/sessions` | Create a consultation session |
| POST | `/sessions/{sid}/transcript` | Submit pre-transcribed text |
| POST | `/sessions/{sid}/simulate` | Smoke-test with canned data |
| POST | `/sessions/{sid}/audio` | Upload audio → batch diarize → pipeline |
| GET | `/sessions/{sid}` | Session status |
| GET | `/sessions/{sid}/outputs/{kind}` | Artifact: raw/clean/extraction/note/risk |
| GET | `/sessions/{sid}/coding` | On-demand ICD-10 hints |
| POST | `/sessions/{sid}/note` | Edit note prose sections |
| PUT | `/sessions/{sid}/extraction` | Edit structured extraction → rebuild note |
| PUT | `/sessions/{sid}/risk` | Edit risk markers |
| POST | `/sessions/{sid}/state` | State transition (draft→…→finalized) |
| GET | `/sessions/{sid}/export/{fmt}` | Export JSON/FHIR/Markdown/PDF |
| WS | `/ws/consultation` | Real-time streaming consult |

### Intelligence, review, admin, versioning (Goals 1,6,7,8,9,10)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/sessions/{sid}/profile` | ConversationProfile (kind, speakers, complexity, confidence) |
| PATCH | `/sessions/{sid}/speakers` | Correct speaker roles/relationship → re-render note |
| POST | `/sessions/{sid}/review` | Doctor verdict (helpful/needs_improvement + categories) |
| GET | `/sessions/{sid}/reviews` | Reviews for a session |
| GET | `/admin/reviews` | Triage queue (filter by status, error_category) |
| PATCH | `/admin/reviews/{admin_id}` | Approve/reject/resolve, assign, notes |
| GET | `/admin/improvements` | Improvement items (filter by stage) |
| POST | `/admin/improvements/{item_id}/advance` | Advance/reject a stage |
| GET / POST | `/prompts` | List / create prompt versions |
| POST | `/prompts/{prompt_id}/activate` | Activate a version |
| GET | `/models` | Model versions |
| POST | `/sessions/{sid}/ai-edit` | AI edit **preview** |
| POST | `/sessions/{sid}/ai-edit/apply` | Apply edit |
| GET | `/sessions/{sid}/edits` | Edit history |
| GET / POST | `/document-templates` | Prescription templates |
| POST | `/sessions/{sid}/document/preview` | Render prescription |
| PUT | `/documents/{doc_id}` | Edit rendered doc |
| POST | `/documents/{doc_id}/approve` | Approve rendered doc |
| GET | `/sessions/{sid}/documents` | Rendered docs for a session |
| GET / POST | `/feature-flags` | List / set flags |

## 5.3 Changes & additions (the redesign)

### Behavioral, not signature changes (most of the value)
These keep the **same endpoint contracts** but change behavior to close the gaps:

| Endpoint | Change |
|----------|--------|
| `POST /prompts/{id}/activate` | **Now invalidates the `PromptProvider` cache** so the pipeline actually uses the activated version (Gap 1). |
| all review/admin/prompt/flag/edit routes | **Now persist** via `SupabaseRepository` when `SCRIBE_STORE_BACKEND=supabase` (Gap 2). |
| `GET /sessions/{sid}/profile` | Response gains `referenced_subjects: [{label, relationship, evidence_span_ids}]` (multi-patient). |
| `PATCH /sessions/{sid}/speakers` | Accepts `referenced_subjects` (not just a single `referenced_patient`). |
| `POST /sessions/{sid}/ai-edit/apply` | Gains `redo` semantics (see new route below). |
| `WS /ws/consultation` `start` frame | Honors `auto: true` → sets `auto_inference_mode` for the session (arms Goal 3). |

### New endpoints
| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| POST | `/sessions/{sid}/ai-edit/undo` | Undo last applied edit (restore `before_enc`) | doctor |
| POST | `/sessions/{sid}/ai-edit/redo` | Redo an undone edit (restore `after_enc`) | doctor |
| POST | `/admin/improvements/{item_id}/eval` | Run the offline eval harness for a candidate prompt over a golden set; writes `eval_runs` + `eval_results` | admin |
| GET | `/admin/improvements/{item_id}/eval` | Fetch eval-run results for the item | admin/auditor |
| GET | `/admin/analytics/errors` | Error-category aggregates over time (for the analytics tab) | admin/auditor |
| GET | `/admin/analytics/latency` | Stage latency percentiles by mode/model (from `stage_latencies`) | admin/auditor |
| GET / POST | `/admin/prompts/{name}/ab` | Get/set A/B split for a prompt (writes a `feature_flags` row) | admin |
| GET | `/admin/prompts/{name}/ab/metrics` | A/B outcome metrics (from `prompt_ab_metrics`) | admin/auditor |

### Representative request/response shapes

**Run an eval (new):**
```http
POST /admin/improvements/{item_id}/eval
{ "candidate_prompt": "…", "dataset": "golden/multispeaker@v1" }

200 OK
{
  "eval_run_id": "er-…",
  "dataset": "golden/multispeaker@v1",
  "n_cases": 24,
  "scores": { "attribution": 0.96, "extraction": 0.91, "risk": 0.88 },
  "passed": true
}
```

**Speaker correction with multi-patient (changed):**
```http
PATCH /sessions/{sid}/speakers
{
  "speakers": [
    {"speaker_label":"speaker_1","role":"caregiver","relationship":"parent","subject_patient":"son"}
  ],
  "referenced_subjects": [
    {"label":"son","relationship":"parent","evidence_span_ids":["seg-3","seg-7"]}
  ]
}

200 OK
{ "note": { … re-rendered … }, "state": "in_review" }
```

## 5.4 WebSocket message contract (unchanged transport)

Server→client events (already in `ws.py` / `ws.ts`): `stage_update`, `final_segment`, `note_chunk`,
`risk_warning`, `analysis`, `draft_ready`, `refined`, `confidence_update`, `mode_switch`, `error`.
Client→server control frames: `{action: start|stop|ping}` (binary frames = PCM16 audio). The
redesign extends only the `start` payload (`auto` flag) and the *content* of `confidence_update` /
`mode_switch` (now sourced from the live `ConversationProfile`).
