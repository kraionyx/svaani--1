# Batch-mode benchmark — clinical@v1

- generated: 2026-06-20T17:28:13+00:00
- model: `gemini-3.5-flash`  ·  template: `general_medicine`  ·  repeat: 1

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
| Speaker Attribution |  25% |  25% | +0% |
| **OVERALL** |  80% |  93% | +14% |

## Latency (ms)

| Stage | p50 | p95 | mean | max |
|---|---:|---:|---:|---:|
| analyze | 61072 | 61072 | 61072 | 61072 |
| note | 4428 | 4428 | 4428 | 4428 |
| risk | 2 | 2 | 2 | 2 |
| total | 65513 | 65513 | 65513 | 65513 |

## Per-case findings

### cardiology-cad-suspected — overall  93%
- (no gaps)
