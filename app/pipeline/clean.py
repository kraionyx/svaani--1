"""Output 2 — clean transcript. Fix obvious STT errors, preserve meaning."""
from __future__ import annotations

from app.config import Settings
from app.llm.base import MedicalLLM
from app.pipeline.prompts import CLEAN_INSTRUCTION, SCRIBE_SYSTEM
from app.schemas.transcript import CleanTranscript, RawTranscript
from app.validation.confidence import low_confidence_span_ids


def clean_transcript(raw: RawTranscript, llm: MedicalLLM, settings: Settings) -> CleanTranscript:
    low_conf = low_confidence_span_ids(raw, settings.stt_low_confidence_threshold)

    if not llm.available:
        # Deterministic fallback: verbatim copy + confidence flags, no corrections.
        return CleanTranscript(
            session_id=raw.session_id,
            segments=list(raw.segments),
            corrections=[],
            low_confidence_span_ids=low_conf,
        )

    prompt = (
        f"{CLEAN_INSTRUCTION}\n\nRaw transcript (JSON):\n{raw.model_dump_json(indent=2)}"
    )
    try:
        clean = llm.generate_structured(prompt, CleanTranscript, system=SCRIBE_SYSTEM)
        clean.session_id = raw.session_id
        # Low-confidence flags are a MEASURED ASR property — always use the gate's
        # values, never the LLM's guess.
        clean.low_confidence_span_ids = low_conf
        return clean
    except Exception:
        return CleanTranscript(
            session_id=raw.session_id,
            segments=list(raw.segments),
            corrections=[],
            low_confidence_span_ids=low_conf,
        )
