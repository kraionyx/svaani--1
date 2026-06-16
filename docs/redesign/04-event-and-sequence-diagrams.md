# 4. Event Flow & Sequence Diagrams

Covers deliverables **#6 (event flow)** and **#8 (sequence diagrams)**.

## 4.1 Real-time consultation (hybrid stream → refine)

```mermaid
sequenceDiagram
    autonumber
    participant D as Doctor (browser)
    participant FE as SPA (ws.ts)
    participant WS as ws.py
    participant STT as Sarvam (stream+batch)
    participant PIPE as orchestrator
    participant PP as PromptProvider
    participant DB as Supabase

    D->>FE: ● Record (Auto mode = on)
    FE->>WS: WS open {action:start, template_id, auto:true}
    WS->>DB: create consultation (state=listening)
    loop live audio
        FE->>WS: PCM16 chunk
        WS->>STT: stream chunk
        STT-->>WS: live segment (unlabeled)
        WS-->>FE: final_segment (live)
    end
    WS-->>FE: note_chunk… (streaming draft sections)
    WS->>PIPE: assess complexity on live transcript
    PIPE-->>WS: ConversationProfile (is_complex?)
    alt auto && complex
        WS-->>FE: mode_switch (→ batch, est 3–5s)
        WS-->>FE: confidence_update (🟡 moderate, reasons)
    end
    D->>FE: ■ Stop
    FE->>WS: {action:stop}
    WS->>STT: batch diarize (final)
    STT-->>WS: diarized RawTranscript
    WS->>PIPE: run_pipeline(raw)
    PIPE->>PP: get_prompt('extract'|'relationship'|…)
    PP-->>PIPE: ACTIVE prompt content (or fallback)
    PIPE-->>WS: PipelineResult (note, profile, risk, grounding)
    WS->>DB: persist session_enc/result_enc + speaker_segments + stage_latencies
    WS-->>FE: refined (final note + speaker timeline)
```

## 4.2 Auto-mode escalation (Goal 3 & 5) — the decision detail

```mermaid
flowchart LR
    T["transcript so far"] --> CX["assess_complexity()"]
    CX --> S{"complexity_score ≥ threshold?"}
    S -->|no| RT["mode = AUTO_REALTIME<br/>keep streaming"]
    S -->|yes| AM{"auto_inference_mode on?"}
    AM -->|no| Keep["keep current mode<br/>(chip shows 🟡 only)"]
    AM -->|yes| B["mode = AUTO_BATCH"]
    B --> N["emit mode_switch notice<br/>(message + est_delay_s:[3,5])"]
    B --> L["record decision → stage_latencies"]
```

Complexity signals (from `app/pipeline/complexity.py`, weights shown):
`extra_speakers .30`, `relationship_ambiguity .20`, `multiple_subjects .20`, `cross_talk .15`,
`pronoun_ambiguity .10`, `poor_audio .20`; score capped at 1.0, complex if `≥ complexity_threshold`.

## 4.3 Relationship resolution — the Mother/Son case (Goal 1)

```mermaid
sequenceDiagram
    autonumber
    participant RAW as diarized transcript
    participant DD as doctor_detect (NEW)
    participant RB as resolve_rule_based
    participant LLM as resolve_llm (sharpen)
    participant PROF as ConversationProfile

    RAW->>DD: segments [spk0:"what happened?", spk1:"my son has fever", …]
    DD->>DD: spk0 asks questions/clinical phrasing → DOCTOR<br/>(not "first seen")
    DD-->>RB: relabeled roles
    RB->>RB: cue "my son" on spk1 → relationship=PARENT, subject="son"
    RB->>RB: referenced_patient = "son"
    alt is_complex (LLM-first)
        RB->>LLM: transcript + RELATIONSHIP_INSTRUCTION (active version)
        LLM-->>RB: {kind:doctor_parent, referenced_patient:son, speakers:[…]}
    end
    RB-->>PROF: kind=DOCTOR_PARENT, referenced_patient=son,<br/>spk1.role=CAREGIVER
    Note over PROF: extraction.referenced_patient = "son"<br/>→ note attributes fever/vomiting to the SON
```

## 4.4 Speaker correction → instant re-render (Goal 6)

```mermaid
sequenceDiagram
    autonumber
    participant D as Doctor
    participant FE as SpeakerTimeline.tsx
    participant API as PATCH /sessions/{id}/speakers
    participant PIPE as rebuild_from_extraction
    participant DB as Supabase
    D->>FE: change spk1 role → Caregiver, subject → father
    FE->>API: {speakers:[…], referenced_patient:"father"}
    API->>DB: update speaker_segments.corrected_role/by/at
    API->>PIPE: re-render note (NO LLM call, ground in flag mode)
    PIPE-->>API: updated note
    API->>DB: persist result_enc
    API-->>FE: {note, state:in_review}
    FE-->>D: note updates in place (attribution → father)
```

## 4.5 AI edit with preview / apply / undo / redo (Goal 11)

```mermaid
sequenceDiagram
    autonumber
    participant D as Doctor
    participant FE as AiEditor.tsx
    participant PRE as POST /ai-edit (preview)
    participant APP as POST /ai-edit/apply
    participant G as Gemini
    participant DB as consultation_edits
    D->>FE: "Move diabetes into past medical history"
    FE->>PRE: instruction + current note
    PRE->>G: edit only requested section, preserve rest
    G-->>PRE: proposed diff (before/after)
    PRE-->>FE: preview (no write)
    D->>FE: Apply
    FE->>APP: confirm
    APP->>DB: insert edit {seq, before_enc, after_enc, applied:true}
    APP-->>FE: updated note + edit seq
    D->>FE: ↶ Undo
    FE->>APP: undo(seq) → mark undone, restore before_enc
    D->>FE: ↷ Redo (NEW)
    FE->>APP: redo(seq) → clear undone, restore after_enc
```

## 4.6 Feedback → admin → improvement (Goals 7→8→9) — event flow

```mermaid
flowchart TD
    R["Doctor: 👎 Needs improvement<br/>+ category=wrong_patient_identified"] --> Rev["consultation_reviews row<br/>(snapshot: model/prompt/mode/conf/spk)"]
    Rev -->|trigger enqueue_admin_review| AR["admin_reviews (pending)"]
    AR --> Adm{"Admin decision"}
    Adm -->|reject| Rej["status=rejected (resolved_at set)"]
    Adm -->|approve| Seed["improvement_items seeded<br/>prompt_name ← category map"]
    Seed --> Pipe["staged pipeline<br/>(human advances each stage)"]
    Pipe --> Eval["eval harness runs candidate over golden set<br/>→ eval_runs + eval_results"]
    Eval --> Gate{"scores pass & human approves?"}
    Gate -->|no| Stop["stage=rejected"]
    Gate -->|yes| Deploy["new prompt_versions row activated<br/>deployed_prompt_version_id set"]
    Deploy --> Live["PromptProvider cache invalidated<br/>→ pipeline uses new version"]
```

`_CATEGORY_TO_PROMPT` (in `app/data/repo.py`) seeds which prompt an error implicates:
`wrong_patient_identified`/`wrong_speaker_assignment` → **relationship**; `incorrect_soap_summary`/
`medication_extraction_error`/`timeline_error`/`missing_diagnosis`/`hallucination` → **extract**;
`prompt_misunderstanding`/`other` → **combined**.

## 4.7 Note finalization & sign-off (state machine)

```mermaid
stateDiagram-v2
    [*] --> listening
    listening --> processing: stop
    processing --> draft: pipeline result
    draft --> in_review: doctor edits / saves
    in_review --> edited: AI edit applied
    edited --> approved: doctor approves
    approved --> finalized: digital sign-off
    in_review --> escalation_required: low confidence / flagged
    finalized --> [*]
```

Export (JSON/FHIR/Markdown/PDF) is allowed only after `finalized` — already enforced in the
sign-off flow.
