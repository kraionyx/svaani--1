# Medical Understanding LLM — comparison & decision

The "Medical Understanding" layer does three narrow jobs: **clean** an STT transcript,
**extract** mentioned entities into a strict schema, and produce **risk markers**. It
never generates clinical content. So the selection criteria are, in order:

1. **Structured-output fidelity** — can it be *forced* to emit our Pydantic schema?
2. **Instruction-following / restraint** — will it refuse to add unsaid content?
3. **PHI data-residency & compliance** — in-country processing, no-training, BAA.
4. **Multilingual / Indian-language competence** (English transcript, but clinical terms).
5. **Cost, latency, operability.**

## Options compared

| | **Gemini on Vertex AI** *(selected)* | Claude (Opus 4.8) | GPT (4-class) | Open-source medical (MedGemma / Llama-3.x / OpenBioLLM) |
|---|---|---|---|---|
| Structured output | **Controlled generation** (`response_schema` ← Pydantic) | Structured outputs (`output_config.format`) + tool strict mode | JSON schema / structured outputs | Varies; needs constrained decoding (Outlines/JSON-mode) |
| Instruction restraint | Strong | Very strong | Strong | Variable, model-dependent |
| Data residency | **`asia-south1` (Mumbai)**, Vertex no-training, Google BAA | Cloud API / Bedrock/Vertex regions; BAA | Cloud API regions; BAA | **Full on-prem** (max control) |
| Context window | Large (long consults) | 1M | Large | Smaller, model-dependent |
| Indian-language terms | Strong | Strong | Strong | Mixed |
| Cost / ops | Pay-per-use; managed | Pay-per-use; managed | Pay-per-use; managed | GPU capex + MLOps burden |
| Fit to *our* constraints | **Already provisioned (user's Vertex key); native schema enforcement; India region** | Excellent quality; would add a second vendor | Excellent quality; second vendor + residency review | Best residency; highest operational cost, lower turnkey quality |

## Decision

**Gemini on Vertex AI**, because it satisfies the binding constraints with the least
friction:

- The user **already has a Vertex AI key** — no new vendor or procurement.
- **Controlled generation** binds our Pydantic schemas directly as `response_schema`, so
  outputs are schema-valid *before* the grounding gate runs (`app/llm/vertex_gemini.py`).
- **`asia-south1` (Mumbai)** keeps PHI inference in-country for DPDPA, with Vertex
  no-training and a Google BAA for HIPAA.
- `temperature=0` for deterministic structuring — we organize, we don't create.

## Why the others are not selected (now)

- **Claude Opus 4.8** is arguably the strongest reasoner and has excellent structured
  outputs and a 1M context, and would be a first-class drop-in — but it adds a second
  vendor when Vertex already meets the need and is the user's chosen stack.
- **GPT-class** is similarly capable but, again, a second vendor plus a separate residency
  review.
- **Open-source medical models** give the best data-residency story (fully on-prem) and
  are the right call under a strict on-prem mandate — at materially higher MLOps cost and
  generally lower turnkey quality for schema-constrained extraction.

## Swappability (no lock-in)

Everything depends only on the `MedicalLLM` protocol (`app/llm/base.py`):

```python
class MedicalLLM(Protocol):
    @property
    def available(self) -> bool: ...
    def generate_structured(self, prompt: str, schema: type[T], *, system: str | None = None) -> T: ...
    def generate_text(self, prompt: str, *, system: str | None = None) -> str: ...
```

Adding Claude, GPT, or a self-hosted model is one new class implementing this protocol and
a branch in `get_llm()`. The pipeline, schemas, grounding gate, and tests are unchanged.

> Note: the selection is about the **understanding** layer only. Speech-to-text is
> **Sarvam V3** (multilingual + diarization → English), independent of the LLM choice.
