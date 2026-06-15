"""Goal 2 & 4 — complexity classifier + confidence band."""
from __future__ import annotations

from app.config import get_settings
from app.pipeline.complexity import assess_complexity
from app.pipeline.subjects import resolve_relationships
from app.schemas.intelligence import ConfidenceBand
from app.schemas.transcript import RawTranscript, SpeakerRole, TranscriptSegment


def _t(rows: list[tuple[SpeakerRole, str, float]]) -> RawTranscript:
    return RawTranscript(
        session_id="s",
        segments=[TranscriptSegment(id=f"seg-{i+1:04d}", speaker=spk, text=txt,
                                    confidence=conf, start_ms=i * 1000, end_ms=i * 1000 + 900)
                  for i, (spk, txt, conf) in enumerate(rows)],
    )


def test_simple_clean_consult_is_high_confidence_not_complex():
    raw = _t([
        (SpeakerRole.DOCTOR, "What brings you in?", 0.98),
        (SpeakerRole.PATIENT, "I have a sore throat.", 0.97),
    ])
    p = resolve_relationships(raw)
    assess_complexity(p, raw, get_settings())
    assert p.is_complex is False
    assert p.confidence_band is ConfidenceBand.HIGH


def test_caregiver_consult_flags_relationship_and_caps_confidence():
    raw = _t([
        (SpeakerRole.DOCTOR, "What happened?", 0.95),
        (SpeakerRole.PATIENT, "My son has had fever for three days.", 0.9),
        (SpeakerRole.OTHER, "And he is also coughing a lot.", 0.6),
    ])
    p = resolve_relationships(raw)
    assess_complexity(p, raw, get_settings())
    # 3 speakers + caregiver present => more complex; confidence cannot be HIGH.
    assert p.complexity_score > 0
    assert p.confidence_band is not ConfidenceBand.HIGH
    assert any("speaker" in s for s in p.complexity_signals)


def test_poor_audio_lowers_confidence():
    raw = _t([
        (SpeakerRole.DOCTOR, "Hello?", 0.3),
        (SpeakerRole.PATIENT, "...inaudible...", 0.2),
    ])
    p = resolve_relationships(raw)
    assess_complexity(p, raw, get_settings())
    assert p.confidence_band is ConfidenceBand.LOW
    assert "poor audio / background noise" in p.confidence_reasons
