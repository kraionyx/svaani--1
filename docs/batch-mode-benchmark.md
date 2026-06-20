# Batch-Mode Accuracy & Latency Benchmark

A reproducible benchmark that runs real consultations through the **batch** pipeline
(`run_pipeline`) and scores clinical-extraction completeness, numeric fidelity, certainty,
and speaker attribution — plus a per-stage latency breakdown. Built to reproduce the
accuracy gaps the team saw on a real cardiology consult, localize the root cause, and
prove a fix.

## Run it

```bash
# Where production stands now (uses the active extract prompt), live Gemini:
python -m app.eval.bench --dataset clinical@v1 --template general_medicine

# Prove the fix — original vs strengthened extract prompt, side by side (repeat to average
# out LLM non-determinism):
python -m app.eval.bench --candidate --template general_medicine --repeat 3

# Hermetic plumbing check (deterministic, no API calls; will NOT reproduce the LLM flaws):
python -m app.eval.bench --mock
```

Reports (console + `report.json` + `report.md`) are written to `docs/benchmarks/<timestamp>/`.
The benchmark scores the **structured `ClinicalExtraction` JSON**, not the rendered note, so
a template that lacks a section can't be blamed for a model that lost a fact.

## What we found

The first surprise: **most of the "missing" content the team saw was not lost by the model.**
On a clean reference transcript rendered against a template that has the right sections, the
baseline extraction already scored **100%** on Past Medical History, Family History,
Investigations, and Numeric Preservation. The losses in the original note came from two
places *outside* the extraction model:

1. **Template-coverage loss (the biggest confound).** The consult was rendered against the
   **ENT** template, which has no Past Medical History, Investigations, Assessment, or
   Family-History section. Diabetes/HTN/smoking, EF 48% / LDL 168 / ST-depression, and the
   suspected-vs-confirmed split had **nowhere to render**, even though the model extracted
   them. Fix: a new `general_medicine` template with those sections, and a Family-History
   section added to `ortho`.
2. **STT garbling (separate layer).** The raw transcript shows `8 years → 80 years`,
   `hypertrophy → apotrophy`, `15 minutes → 50 minutes`, and speaker swaps. The clean stage
   is forbidden from changing numbers, so it can't repair an STT mishear. This is a Sarvam /
   diarization issue, not an extraction issue — out of scope here, surfaced as a separate
   axis (see Follow-ups).

The genuine **extraction** weaknesses — and the strengthened `extract` prompt's effect on
them (live Gemini, `--repeat 3`):

| Axis | Baseline | Candidate |
|---|---:|---:|
| Symptoms / PMH / Family Hx / Investigations / Numeric | 100% | 100% |
| **Differentials** (AF / SVT / PVC named for palpitations) | **0%** | **100%** |
| **Certainty** (suspected ischemia kept out of confirmed diagnosis) | **50%** | **100%** |
| Speaker Attribution | 75% | 75% |
| **OVERALL** | **84%** | **98%** |

- **Certainty (the safety-relevant one):** the baseline upgraded "positive TMT *suggests
  possibility of* myocardial ischemia" into a **confirmed diagnosis**. The strengthened
  prompt keeps suspected findings in `assessment` and only confirmed conditions in
  `diagnosis`. The scorer penalizes only the dangerous direction (over-claiming certainty);
  filing a confirmed finding under "assessment" is treated as captured, not an error.
- **Differentials:** the baseline dropped the named arrhythmia differential; the candidate
  records it.
- **Speaker attribution (75%):** doctor, patient, and the referenced patient resolve
  correctly, but the **wife/caregiver is collapsed into a generic "other"** rather than
  `caregiver`. Real gap, independent of the extract prompt.

### Latency finding

| stage | p50 (ms) |
|---|---:|
| analyze (clean+extract+risk) | ~59,000 |
| note (narrate) | ~3,600 |
| total | ~62,000 |

`analyze` dominates at ~60s. Root cause: the single-pass "combined" call
(`app/pipeline/combined.py`) asks the model to return the **entire clean transcript +
extraction + risk** in one structured response. On a real-length consult (~49 segments) that
output exceeds `llm_max_output_tokens` (8192) → the response is truncated (`MAX_TOKENS`),
`resp.text` is empty, and the call **silently falls back to the 3-call staged pipeline**
(`single-pass analysis failed; falling back to staged pipeline`). So batch pays for a failed
combined call *plus* three sequential round-trips. This is the bulk of the "batch is slow"
complaint.

## What changed in this work

- **Benchmark harness** (`app/eval/`): `clinical_scorer.py`, `clinical_runner.py`, `bench.py`,
  dataset `datasets/clinical_v1/`, regression test `tests/test_clinical_bench.py`.
- **Per-stage latency**: `PipelineResult.timings_ms` + stage timing in `run_pipeline`;
  `_process` now records per-stage rows so `GET /admin/analytics/latency` shows the breakdown.
- **Strengthened `extract` prompt** (`app/pipeline/prompts.py`): demands PMH, family history,
  investigations with verbatim numerics, number preservation, and a suspected-vs-confirmed
  split. Flows into the batch single-pass path automatically. Rolled out as `extract@v2`
  (active); the original is kept as `EXTRACT_INSTRUCTION_V1_BASELINE` for the benchmark.
- **Templates**: new `docs/templates/general_medicine.json`; `FAMILY_HISTORY` added to
  `docs/templates/ortho.json`. (A running server must restart to load template changes.)

## Follow-ups (surfaced, not yet done)

1. **Batch latency**: stop re-emitting the full clean transcript in the combined call
   (return corrections only and reconstruct clean), or gate single-pass by transcript length
   so long consults skip the doomed combined call. Either reclaims ~30–40s.
2. **Caregiver attribution**: teach `app.pipeline.subjects` to resolve a spouse/parent
   speaker to `caregiver` instead of `other`.
3. **STT numeric fidelity**: an audio-in WER / numeric-fidelity axis (and Sarvam config
   review) for `8y→80y` style mishears that the LLM cannot repair.
4. **Dataset breadth**: add more cases (other specialties, denials/negation, multi-patient)
   so the scorecard generalizes beyond the one cardiology consult.
```
