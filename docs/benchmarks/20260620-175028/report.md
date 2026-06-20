# Batch-mode benchmark — clinical@v1

- generated: 2026-06-20T17:50:28+00:00
- model: `gemini-3.5-flash`  ·  template: `general_medicine`  ·  repeat: 3

## Scorecard — baseline vs candidate (strengthened extract prompt)

| Axis | Baseline | Candidate | Δ |
|---|---:|---:|---:|
| Symptoms | 100% | 100% | +0% |
| Past Medical History / Risk Factors | 100% | 100% | +0% |
| Family History | 100% | 100% | +0% |
| Investigations | 100% | 100% | +0% |
| Assessment (suspected) | 100% | 100% | +0% |
| Diagnosis (confirmed) | 100% | 100% | +0% |
| Treatment Plan | 100% | 100% | +0% |
| Differentials |   0% | 100% | +100% |
| Numeric Preservation | 100% | 100% | +0% |
| Certainty |  50% | 100% | +50% |
| Speaker Attribution |  75% |  75% | +0% |
| **OVERALL** |  84% |  98% | +14% |

## Latency (ms)

| Stage | p50 | p95 | mean | max |
|---|---:|---:|---:|---:|
| analyze | 58324 | 62647 | 59904 | 63127 |
| note | 3613 | 3715 | 3599 | 3726 |
| risk | 2 | 2 | 2 | 2 |
| total | 61998 | 66140 | 63516 | 66600 |

## Per-case findings

### cardiology-cad-suspected — overall  98%
- (no gaps)
