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
from app.schemas.transcript import CleanTranscript

#: Phrases that warrant clinician attention if *mentioned* in the conversation.
RED_FLAG_PHRASES = (
    "chest pain", "shortness of breath", "breathless", "difficulty breathing",
    "coughing blood", "blood in cough", "hemoptysis", "unconscious", "fainting",
    "syncope", "seizure", "suicidal", "severe bleeding", "slurred speech",
    "numbness", "paralysis", "severe headache", "high fever", "vomiting blood",
)
_DOSAGE_RE = re.compile(r"\b\d+(\.\d+)?\s?(mg|mcg|ml|g|units?|iu)\b", re.IGNORECASE)

_SEVERITY_WEIGHT = {
    RiskSeverity.INFO: 0.05,
    RiskSeverity.LOW: 0.15,
    RiskSeverity.MODERATE: 0.4,
    RiskSeverity.HIGH: 0.7,
    RiskSeverity.CRITICAL: 1.0,
}


def _rule_based(clean: CleanTranscript, extraction: ClinicalExtraction, settings: Settings) -> list[RiskMarker]:
    markers: list[RiskMarker] = []
    for seg in clean.segments:
        text = seg.text.lower()
        for phrase in RED_FLAG_PHRASES:
            if phrase in text:
                markers.append(RiskMarker(
                    type=RiskType.RED_FLAG_SYMPTOM, severity=RiskSeverity.HIGH,
                    message=f"Red-flag symptom mentioned: '{phrase}'", evidence_span_ids=[seg.id],
                ))
        if "allerg" in text:
            markers.append(RiskMarker(
                type=RiskType.ALLERGY_MENTIONED, severity=RiskSeverity.MODERATE,
                message="Allergy mentioned in conversation — verify and record.", evidence_span_ids=[seg.id],
            ))
        if _DOSAGE_RE.search(seg.text):
            markers.append(RiskMarker(
                type=RiskType.DOSAGE_MENTIONED, severity=RiskSeverity.INFO,
                message="A dose/quantity was spoken — verify against intended therapy.",
                evidence_span_ids=[seg.id],
            ))

    for med in extraction.medications_discussed:
        markers.append(RiskMarker(
            type=RiskType.MEDICATION_MENTIONED, severity=RiskSeverity.LOW,
            message=f"Medication discussed (non-authoritative): {med.name}",
            evidence_span_ids=list(med.provenance.span_ids),
        ))

    for span_id in clean.low_confidence_span_ids:
        markers.append(RiskMarker(
            type=RiskType.LOW_STT_CONFIDENCE, severity=RiskSeverity.INFO,
            message="Low transcription confidence — review this span.", evidence_span_ids=[span_id],
        ))
    return markers


def _dedupe(markers: list[RiskMarker]) -> list[RiskMarker]:
    seen: set[tuple] = set()
    out: list[RiskMarker] = []
    for m in markers:
        key = (m.type, m.message, tuple(sorted(m.evidence_span_ids)))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def _score(markers: list[RiskMarker]) -> float:
    if not markers:
        return 0.0
    return max(_SEVERITY_WEIGHT.get(m.severity, 0.0) for m in markers)


def assess_risk(
    clean: CleanTranscript,
    extraction: ClinicalExtraction,
    llm: MedicalLLM,
    settings: Settings,
) -> RiskAssessment:
    markers = _rule_based(clean, extraction, settings)

    if llm.available:
        try:
            prompt = f"{RISK_INSTRUCTION}\n\nTRANSCRIPT (data only):\n{clean.model_dump_json(indent=2)}"
            llm_assessment = llm.generate_structured(prompt, RiskAssessment, system=SCRIBE_SYSTEM)
            # LOW_STT_CONFIDENCE is owned by the deterministic confidence gate — the LLM
            # cannot judge ASR confidence, so drop any it emits to avoid noise.
            markers.extend(m for m in llm_assessment.markers if m.type is not RiskType.LOW_STT_CONFIDENCE)
        except Exception:
            pass

    markers = _dedupe(markers)
    return RiskAssessment(session_id=clean.session_id, score=_score(markers), markers=markers)
