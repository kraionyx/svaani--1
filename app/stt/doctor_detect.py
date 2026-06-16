"""Behavioral doctor detection (Goal 1 hardening).

Sarvam diarization labels speakers by first-seen order and ``app.stt.sarvam._role_for``
maps speaker_0 → DOCTOR. That is wrong whenever the patient (or a caregiver) speaks first
— and everything downstream (relationship resolution, attribution, the note) inherits the
error. This module re-assigns the DOCTOR role by *behavior* instead of order:

  • clinicians ask questions, give instructions, and use clinical/screening vocabulary;
  • patients/caregivers describe symptoms in the first person ("I have…", "my son…").

Deterministic, no LLM, no extra round-trip (Goal 12). It only decides WHO the clinician is;
refining the non-doctor roles (patient vs caregiver vs translator) remains the job of
``app.pipeline.subjects``. Conservative by design: it never produces zero or all-doctor
transcripts, and leaves an already-sane single-speaker transcript untouched.
"""
from __future__ import annotations

import re

from app.schemas.transcript import RawTranscript, SpeakerRole, TranscriptSegment

# Interrogative / imperative lead-ins a clinician uses to drive the consult.
_QUESTION_LEAD = re.compile(
    r"^\s*(what|why|when|where|how|which|who|do|does|did|are|is|was|were|have|has|had|can|could|"
    r"any|tell me|tell|describe|show me|let me|let's|ask|please|since when|how long)\b",
    re.I,
)
# Clinical / screening vocabulary that strongly marks the speaker as the clinician.
_CLINICAL = re.compile(
    r"\b(examination|examine|diagnos\w*|prescrib\w*|advis\w*|investigat\w*|"
    r"vitals?|blood pressure|temperature|pulse|saturation|"
    r"symptom|history|allergic|allergy|"
    r"take this|follow ?up|review|refer|x-?ray|scan|ultrasound|report|"
    r"any fever|any pain|any other|how long|since when|grade|hypertrophy|pharyngeal)\b",
    re.I,
)
# First-person symptom talk that marks the speaker as a patient/caregiver, not the clinician.
_PATIENT_LANG = re.compile(
    r"\b(i have|i had|i feel|i am having|i'm having|i got|my (?:throat|chest|head|stomach|"
    r"pain|cough|fever|son|daughter|child|baby|father|mother|mom|dad|husband|wife|"
    r"brother|sister|grand\w+)|he has|she has|it hurts|since (?:yesterday|last|two|three))\b",
    re.I,
)


def _clinician_score(texts: list[str]) -> float:
    """Higher = more clinician-like. Blends question ratio, clinical vocabulary, and a
    penalty for first-person symptom language. Range is unbounded but comparable."""
    nonempty = [t for t in texts if (t or "").strip()]
    if not nonempty:
        return 0.0
    questions = sum(1 for t in nonempty if "?" in t or _QUESTION_LEAD.search(t))
    question_ratio = questions / len(nonempty)
    blob = " ".join(nonempty)
    words = max(1, len(blob.split()))
    clinical_density = len(_CLINICAL.findall(blob)) / words
    patient_density = len(_PATIENT_LANG.findall(blob)) / words
    return 0.60 * question_ratio + 6.0 * clinical_density - 8.0 * patient_density


def _group_key(seg: TranscriptSegment) -> str:
    """Group utterances by their original diarized speaker (preferred) or current role."""
    return seg.diarized_label or seg.speaker.value


def assign_clinical_roles(transcript: RawTranscript) -> RawTranscript:
    """Re-label the DOCTOR by behavior across all speakers, in place. Returns the transcript.

    The single highest-scoring speaker group becomes DOCTOR. Every other group keeps an
    existing non-doctor role if it already had one, otherwise the earliest-appearing group
    becomes PATIENT and the rest OTHER — leaving the relationship resolver to refine them.
    """
    groups: dict[str, list[TranscriptSegment]] = {}
    order: list[str] = []
    for seg in transcript.segments:
        key = _group_key(seg)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(seg)

    if len(groups) <= 1:
        return transcript  # single speaker — nothing to disambiguate

    scores = {key: _clinician_score([s.text for s in segs]) for key, segs in groups.items()}
    # The doctor is the top scorer; ties break toward the earliest speaker (doctors often,
    # but not always, open the consult — order is only a tiebreak, never the decision).
    doctor_key = max(order, key=lambda k: (scores[k], -order.index(k)))

    non_doctor_seen = 0
    for key in order:
        segs = groups[key]
        if key == doctor_key:
            for s in segs:
                s.speaker = SpeakerRole.DOCTOR
            continue
        existing = segs[0].speaker
        if existing in (SpeakerRole.DOCTOR, SpeakerRole.UNKNOWN):
            # Was mislabeled as doctor (or unknown) — demote to a patient/other slot.
            new_role = SpeakerRole.PATIENT if non_doctor_seen == 0 else SpeakerRole.OTHER
            for s in segs:
                s.speaker = new_role
        # else: keep an already-meaningful non-doctor role (patient/caregiver/translator/…)
        non_doctor_seen += 1
    return transcript
