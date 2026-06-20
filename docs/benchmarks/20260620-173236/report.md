# Batch-mode benchmark — clinical@v1

- generated: 2026-06-20T17:32:36+00:00
- model: `gemini-3.5-flash`  ·  template: `general_medicine`  ·  repeat: 1

## Scorecard — baseline vs candidate (strengthened extract prompt)

| Axis | Baseline | Candidate | Δ |
|---|---:|---:|---:|
| Symptoms | 100% | 100% | +0% |
| Past Medical History / Risk Factors | 100% | 100% | +0% |
| Family History | 100% | 100% | +0% |
| Investigations | 100% | 100% | +0% |
| Assessment (suspected) | 100% | 100% | +0% |
| Diagnosis (confirmed) | 100% |   0% | -100% |
| Treatment Plan | 100% | 100% | +0% |
| Differentials |   0% | 100% | +100% |
| Numeric Preservation | 100% | 100% | +0% |
| Certainty |  50% | 100% | +50% |
| Speaker Attribution |  75% |  75% | +0% |
| **OVERALL** |  84% |  89% | +5% |

## Latency (ms)

| Stage | p50 | p95 | mean | max |
|---|---:|---:|---:|---:|
| analyze | 59165 | 59165 | 59165 | 59165 |
| note | 3443 | 3443 | 3443 | 3443 |
| risk | 1 | 1 | 1 | 1 |
| total | 62620 | 62620 | 62620 | 62620 |

## Per-case findings

### cardiology-cad-suspected — overall  89%
- Diagnosis (confirmed): left ventricular hypertrophy (misfiled)
- Diagnosis (confirmed): dyslipidemia (misfiled)
