"""Goal 2 & 4 — conversation complexity + confidence.

A lightweight, deterministic classifier (no LLM, no extra round-trip) that estimates
how hard a consultation is to document accurately, and a confidence band for the
accuracy indicator. Both run on the transcript we already have, so they add no latency
to simple consults (Goal 12).

Complexity drives the real-time/batch decision (Goal 3); confidence drives the
🟢/🟡/🔴 indicator (Goal 4). Neither asserts any clinical content.
"""
from __future__ import annotations

import re

from app.config import Settings
from app.schemas.intelligence import (
    ConfidenceBand,
    ConversationProfile,
    SpeakerRelationship,
)
from app.schemas.transcript import CleanTranscript, RawTranscript, SpeakerRole

#: Each signal contributes a weighted amount to the [0,1] complexity score.
_WEIGHTS = {
    "extra_speakers": 0.30,        # > 2 unique speakers
    "relationship_ambiguity": 0.20,
    "multiple_subjects": 0.20,
    "cross_talk": 0.15,            # overlapping segments / interruptions
    "pronoun_ambiguity": 0.10,
    "poor_audio": 0.20,            # low mean ASR confidence
}

_PRONOUN_RE = re.compile(r"\b(he|she|they|him|her|his|their|them)\b", re.I)


def _mean_confidence(transcript: RawTranscript | CleanTranscript) -> float:
    segs = [s for s in transcript.segments if (s.text or "").strip()]
    if not segs:
        return 1.0
    return sum(s.confidence for s in segs) / len(segs)


def _cross_talk(transcript: RawTranscript | CleanTranscript) -> int:
    """Count segments that start before the previous one ends (overlap / interruption)."""
    overlaps = 0
    prev_end = None
    for s in sorted(transcript.segments, key=lambda x: x.start_ms):
        if prev_end is not None and s.start_ms < prev_end and s.end_ms > s.start_ms:
            overlaps += 1
        prev_end = max(prev_end or 0, s.end_ms)
    return overlaps


def assess_complexity(
    profile: ConversationProfile,
    transcript: RawTranscript | CleanTranscript,
    settings: Settings,
) -> ConversationProfile:
    """Populate ``complexity_*`` and ``confidence_*`` on the profile, in place."""
    signals: list[str] = []
    score = 0.0

    # 1) More than doctor + patient.
    if profile.speaker_count > 2:
        score += _WEIGHTS["extra_speakers"]
        signals.append(f"{profile.speaker_count} speakers detected")

    # 2) A caregiver/translator is present (the speaker is not the patient).
    non_doctor = [s for s in profile.speakers if s.role is not SpeakerRole.DOCTOR]
    if any(s.relationship in {SpeakerRelationship.UNKNOWN} for s in non_doctor):
        score += _WEIGHTS["relationship_ambiguity"]
        signals.append("relationship ambiguity")
    if any(s.role is SpeakerRole.CAREGIVER or s.role is SpeakerRole.TRANSLATOR for s in non_doctor):
        signals.append("patient is spoken for by a caregiver/translator")

    # 3) Multiple distinct referenced patients.
    subjects = {s.subject_patient for s in non_doctor if s.subject_patient}
    if len(subjects) > 1:
        score += _WEIGHTS["multiple_subjects"]
        signals.append(f"multiple referenced patients: {', '.join(sorted(subjects))}")

    # 4) Cross-talk / interruptions.
    overlaps = _cross_talk(transcript)
    if overlaps:
        score += min(_WEIGHTS["cross_talk"], 0.05 * overlaps)
        signals.append(f"{overlaps} overlapping/interrupted turn(s)")

    # 5) Pronoun ambiguity when more than one person is in the room.
    if profile.speaker_count > 2 or subjects:
        pron = sum(len(_PRONOUN_RE.findall(s.text or "")) for s in transcript.segments)
        if pron >= 4:
            score += _WEIGHTS["pronoun_ambiguity"]
            signals.append("frequent ambiguous pronouns")

    # 6) Audio quality (ASR confidence proxy for diarization confidence + background noise).
    mean_conf = _mean_confidence(transcript)
    if mean_conf < settings.stt_low_confidence_threshold:
        score += _WEIGHTS["poor_audio"]
        signals.append("low transcription confidence / background noise")

    profile.complexity_score = min(1.0, round(score, 3))
    profile.is_complex = profile.complexity_score >= settings.complexity_threshold
    profile.complexity_signals = signals

    # ── Confidence band (Goal 4) ───────────────────────────────────────────────
    # Blend audio confidence with complexity: a clean but complex consult is still only
    # moderately trustworthy for automated documentation.
    profile.audio_confidence = round(mean_conf, 3)
    reasons: list[str] = []
    band_value = mean_conf
    if profile.is_complex:
        band_value = min(band_value, settings.confidence_moderate_threshold)  # cap at moderate
    if profile.speaker_count > 2:
        reasons.append("multiple speakers")
    if any(s.relationship is SpeakerRelationship.UNKNOWN for s in non_doctor):
        reasons.append("relationship ambiguity")
    if mean_conf < settings.stt_low_confidence_threshold:
        reasons.append("poor audio / background noise")
    if overlaps:
        reasons.append("cross-talk")

    if band_value >= settings.confidence_high_threshold and not profile.is_complex:
        profile.confidence_band = ConfidenceBand.HIGH
    elif band_value >= settings.confidence_moderate_threshold:
        profile.confidence_band = ConfidenceBand.MODERATE
    else:
        profile.confidence_band = ConfidenceBand.LOW
    profile.confidence_reasons = reasons
    return profile
