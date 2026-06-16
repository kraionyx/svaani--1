# Svaani Scribe — Intelligent Redesign (Design Document)

Design deliverable for hardening multi-speaker clinical accuracy while preserving the existing
low-latency UX. **No code has been changed** — this is the design to review before implementation.

Read in order:

1. [00-overview.md](00-overview.md) — problem, what exists, the 4 structural gaps, principles
2. [01-system-architecture.md](01-system-architecture.md) — system + backend architecture, AI orchestration (#1, #2, #9)
3. [02-frontend-flow.md](02-frontend-flow.md) — frontend flow + UI wireframes (#3, #4)
4. [03-data-model.md](03-data-model.md) — database schema + additive changes (#5)
5. [04-event-and-sequence-diagrams.md](04-event-and-sequence-diagrams.md) — event flow + sequence diagrams (#6, #8)
6. [05-api-design.md](05-api-design.md) — REST + WS API catalog and changes (#7)
7. [06-feedback-and-improvement-pipeline.md](06-feedback-and-improvement-pipeline.md) — feedback learning + eval harness (#10)
8. [07-admin-dashboard.md](07-admin-dashboard.md) — admin console design (#11)
9. [08-nonfunctional.md](08-nonfunctional.md) — deployment, scalability, security, performance, risks (#12–#16)
10. [09-enterprise-architecture-review.md](09-enterprise-architecture-review.md) — adversarial architecture review + SOTA-2026 target, STT vendor shoot-out, benchmarking framework, cost tiers, migration plan

## The thesis in one paragraph

Most of the 13 goals are already scaffolded. The real problem is that they are **disconnected**
(activating a prompt version changes nothing — the pipeline imports prompt strings directly),
**non-persistent** (reviews/admin/improvements/prompts/flags/edits live in RAM), and **unhardened**
(the resolver trusts Sarvam's speaker order and collapses multiple referenced patients into one).
The redesign makes every goal **connected + persistent + hardened**, governed by a human-gated
improvement loop with a real offline regression-eval harness. Implementation phases B–F are in the
approved plan (`.claude/plans/…`).
