"""Output 5 (revised) — risk markers / risk score.

A rule-based detector provides a deterministic baseline (runs with no LLM); when a
Medical LLM is available its findings are merged in. Every marker cites the
transcript spans that triggered it. NON-AUTHORITATIVE: it highlights for the doctor;
it never diagnoses, recommends, or prescribes.
"""
from __future__ import annotations

import re

from app.config import Settings
from app.llm.base import MedicalLLM
from app.pipeline.prompts import RISK_INSTRUCTION, SCRIBE_SYSTEM
from app.schemas.clinical import ClinicalExtraction
from app.schemas.risk import RiskAssessment, RiskMarker, RiskSeverity, RiskType
from app.schemas.transcript import CleanTranscript, SpeakerRole

#: Phrases that warrant clinician attention if *mentioned* in the conversation.
RED_FLAG_PHRASES = (
    "chest pain", "shortness of breath", "breathless", "difficulty breathing",
    "coughing blood", "blood in cough", "hemoptysis", "unconscious", "fainting",
    "syncope", "seizure", "suicidal", "severe bleeding", "slurred speech",
    "numbness", "paralysis", "severe headache", "high fever", "vomiting blood",
)
_DOSAGE_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:mg|mcg|ml|g|units?|iu)\b", re.IGNORECASE)
#: Words that negate a nearby mention ("no allergies", "denies chest pain").
_NEGATION_RE = re.compile(r"\b(no|not|without|none|negative|nil|denies|deny|denied)\b", re.IGNORECASE)
#: A doctor utterance that is a screening question, not a reported finding.
_QUESTION_RE = re.compile(r"\?|\b(do you|are you|have you|any other|is there)\b", re.IGNORECASE)


def _snippet(text: str, limit: int = 160) -> str:
    """One-line, length-capped quote of a transcript span for marker context."""
    s = " ".join((text or "").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"

_SEVERITY_WEIGHT = {
    RiskSeverity.INFO: 0.05,
    RiskSeverity.LOW: 0.15,
    RiskSeverity.MODERATE: 0.4,
    RiskSeverity.HIGH: 0.7,
    RiskSeverity.CRITICAL: 1.0,
}


def _rule_based(clean: CleanTranscript, extraction: ClinicalExtraction, settings: Settings) -> list[RiskMarker]:
    markers: list[RiskMarker] = []
    seg_text = {s.id: s.text for s in clean.segments}
    for seg in clean.segments:
        text = seg.text.lower()
        negated = bool(_NEGATION_RE.search(text))
        quote = _snippet(seg.text)
        for phrase in RED_FLAG_PHRASES:
            if phrase in text:
                # A denied red flag ("no chest pain") is reassurance, not a risk.
                markers.append(RiskMarker(
                    type=RiskType.RED_FLAG_SYMPTOM,
                    severity=RiskSeverity.INFO if negated else RiskSeverity.HIGH,
                    message=(f"Red-flag symptom '{phrase}' reported as ABSENT — for context."
                             if negated else f"Red-flag symptom mentioned: '{phrase}'."),
                    evidence_span_ids=[seg.id], evidence_text=quote,
                ))
        if "allerg" in text:
            # The doctor's screening question is not a finding — skip it.
            is_question = seg.speaker is SpeakerRole.DOCTOR and bool(_QUESTION_RE.search(seg.text))
            if not is_question:
                markers.append(RiskMarker(
                    type=RiskType.ALLERGY_MENTIONED,
                    severity=RiskSeverity.INFO if negated else RiskSeverity.MODERATE,
                    message=("No allergies reported by the patient — for the record."
                             if negated else "Allergy mentioned in conversation — verify and record."),
                    evidence_span_ids=[seg.id], evidence_text=quote,
                ))
        for dm in _DOSAGE_RE.finditer(seg.text):
            markers.append(RiskMarker(
                type=RiskType.DOSAGE_MENTIONED, severity=RiskSeverity.INFO,
                message=f"Dose/quantity spoken: '{dm.group(0)}' — verify against intended therapy.",
                evidence_span_ids=[seg.id], evidence_text=quote,
            ))

    for med in extraction.medications_discussed:
        spans = list(med.provenance.span_ids)
        dose = f" {med.dose}" if med.dose else ""
        markers.append(RiskMarker(
            type=RiskType.MEDICATION_MENTIONED, severity=RiskSeverity.LOW,
            message=f"Medication discussed (non-authoritative): {med.name}{dose}.",
            evidence_span_ids=spans,
            evidence_text=med.verbatim_text or _snippet(" ".join(seg_text.get(s, "") for s in spans)),
        ))

    for span_id in clean.low_confidence_span_ids:
        markers.append(RiskMarker(
            type=RiskType.LOW_STT_CONFIDENCE, severity=RiskSeverity.INFO,
            message="Low transcription confidence — review this span.",
            evidence_span_ids=[span_id], evidence_text=_snippet(seg_text.get(span_id, "")),
        ))
    return markers


def _dedupe(markers: list[RiskMarker]) -> list[RiskMarker]:
    """Collapse markers that say the same thing, merging their evidence spans.

    Keying on (type, message) — rather than (type, message, spans) — merges the
    repeats the user saw (e.g. a doctor's "allerg" question + the patient's answer,
    or the same generic line emitted by both the rule pass and the LLM), unioning
    their span ids instead of listing the marker twice.
    """
    out: list[RiskMarker] = []
    by_key: dict[tuple, RiskMarker] = {}
    for m in markers:
        key = (m.type, m.message.strip().lower())
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = m
            out.append(m)
            continue
        for sid in m.evidence_span_ids:
            if sid not in existing.evidence_span_ids:
                existing.evidence_span_ids.append(sid)
        if not existing.evidence_text and m.evidence_text:
            existing.evidence_text = m.evidence_text
    return out


def _score(markers: list[RiskMarker]) -> float:
    if not markers:
        return 0.0
    return max(_SEVERITY_WEIGHT.get(m.severity, 0.0) for m in markers)


def aggregate_score(markers: list[RiskMarker]) -> float:
    """Public alias for the aggregate attention score (used when risk is hand-edited)."""
    return _score(markers)


def llm_risk_markers(clean: CleanTranscript, llm: MedicalLLM) -> list[RiskMarker]:
    """LLM-derived risk markers.

    Depends only on ``clean`` (not the extraction), so the orchestrator can run it
    concurrently with ``extract_clinical`` to save a round-trip. Returns ``[]`` on
    any failure or when no LLM is configured — risk never blocks the note.
    """
    if not llm.available:
        return []
    try:
        prompt = f"{RISK_INSTRUCTION}\n\nTRANSCRIPT (data only):\n{clean.model_dump_json(indent=2)}"
        assessment = llm.generate_structured(prompt, RiskAssessment, system=SCRIBE_SYSTEM)
        # Some marker types are owned by deterministic passes, so drop any the LLM emits
        # to avoid double-listing the same item:
        #  • LOW_STT_CONFIDENCE — the confidence gate measures ASR confidence; the LLM can't.
        #  • MEDICATION_MENTIONED / DOSAGE_MENTIONED — derived verbatim from the grounded
        #    extraction by the rule pass (the LLM duplicated these, often with wrong doses).
        _owned = {RiskType.LOW_STT_CONFIDENCE, RiskType.MEDICATION_MENTIONED, RiskType.DOSAGE_MENTIONED}
        return [m for m in assessment.markers if m.type not in _owned]
    except Exception:
        return []


def assess_risk(
    clean: CleanTranscript,
    extraction: ClinicalExtraction,
    llm: MedicalLLM,
    settings: Settings,
    *,
    llm_markers: list[RiskMarker] | None = None,
) -> RiskAssessment:
    markers = _rule_based(clean, extraction, settings)
    # ``llm_markers`` lets the caller supply markers computed in parallel; falling
    # back to a synchronous call keeps assess_risk usable standalone (tests, REST).
    markers.extend(llm_markers if llm_markers is not None else llm_risk_markers(clean, llm))

    markers = _dedupe(markers)
    return RiskAssessment(session_id=clean.session_id, score=_score(markers), markers=markers)
