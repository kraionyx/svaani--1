"""Risk markers surface conversation-present risks; they never diagnose."""
from __future__ import annotations

from app.config import get_settings
from app.llm.base import DisabledLLM
from app.pipeline.risk import assess_risk
from app.schemas.clinical import ClinicalExtraction
from app.schemas.risk import RiskType
from app.schemas.transcript import CleanTranscript, SpeakerRole, TranscriptSegment


def _clean(text: str, conf: float = 0.95) -> CleanTranscript:
    return CleanTranscript(
        session_id="s",
        segments=[TranscriptSegment(id="seg-0001", speaker=SpeakerRole.PATIENT, text=text, confidence=conf)],
        low_confidence_span_ids=[],
    )


def test_red_flag_symptom_is_flagged():
    clean = _clean("I have chest pain since this morning.")
    assessment = assess_risk(clean, ClinicalExtraction(session_id="s"), DisabledLLM(), get_settings())

    red = [m for m in assessment.markers if m.type is RiskType.RED_FLAG_SYMPTOM]
    assert red, "expected a red-flag marker for 'chest pain'"
    assert "seg-0001" in red[0].evidence_span_ids
    assert red[0].authoritative is False
    assert assessment.score > 0.5


def test_benign_conversation_has_no_red_flags():
    clean = _clean("I have a mild runny nose for a day.")
    assessment = assess_risk(clean, ClinicalExtraction(session_id="s"), DisabledLLM(), get_settings())

    assert not [m for m in assessment.markers if m.type is RiskType.RED_FLAG_SYMPTOM]
